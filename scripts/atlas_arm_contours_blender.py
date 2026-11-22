"""Compare surface intersection lengths when mesh resolutions differ."""

import json
from pathlib import Path
import sys

import bpy
import numpy as np

from atlas_arm_review_blender import check_arm_bone_pose
from atlas_arm_surface_blender import self_pairs, topology
from atlas_collision_blender import ATLAS, rendered_meshes, surface, tree


def line_intervals(poly, other, normals, direction, valid):
    signed = np.einsum("nvc,nc->nv", poly - other[:, :1], normals)
    follow = np.roll(signed, -1, axis=1)
    start = np.einsum("nvc,nc->nv", poly, direction)
    end = np.roll(start, -1, axis=1)
    crossing = ((signed < -1e-10) & (follow > 1e-10)) | ((signed > 1e-10) & (follow < -1e-10))
    fraction = np.divide(signed, signed - follow, out=np.zeros_like(signed), where=crossing)
    projected = np.concatenate((start, start + fraction * (end - start)), axis=1)
    flags = np.concatenate((np.abs(signed) <= 1e-10, crossing), axis=1) & valid[:, None]
    return np.min(np.where(flags, projected, np.inf), axis=1), np.max(np.where(flags, projected, -np.inf), axis=1)


def intersection_length(a, b):
    na, nb = (np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]) for t in (a, b))
    wa, wb = (np.linalg.norm(n, axis=1) for n in (na, nb))
    use = (wa > 1e-14) & (wb > 1e-14)
    na, nb = (np.divide(n, w[:, None], out=np.zeros_like(n), where=use[:, None])
              for n, w in ((na, wa), (nb, wb)))
    axis = np.cross(na, nb)
    scale = np.linalg.norm(axis, axis=1)
    use &= scale > 1e-8
    axis = np.divide(axis, scale[:, None], out=np.zeros_like(axis), where=use[:, None])
    l1, h1 = line_intervals(a, b, nb, axis, use)
    l2, h2 = line_intervals(b, a, na, axis, use)
    return float(np.maximum(0, np.minimum(h1, h2) - np.maximum(l1, l2)).sum())


def check():
    base = np.array([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]])
    crossing = np.array([[[.25, .25, -.5], [.25, .25, .5], [.25, 1.25, 0.]]])
    assert abs(intersection_length(base, crossing) - .5) < 1e-9
    assert intersection_length(base, crossing + 2) == 0
    assert intersection_length(base, base) == 0


def measure(scene, expected, labels):
    check()
    layers = scene.collection.children
    muscles = {obj["source_label"]: obj for obj in rendered_meshes(layers[ATLAS])}
    rows = []
    for record in expected["frames"]:
        scene.frame_set(record["frame"])
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        check_arm_bone_pose(record, graph)
        bones = []
        for obj in rendered_meshes(layers["bones"]):
            points, faces = surface(obj, graph)
            bones.append((obj.name, points.min(0), points.max(0), points[faces], tree(points, faces)))
        frame = {}
        for label in labels:
            obj = muscles[label]
            points, faces = surface(obj, graph)
            bvh, triangles = tree(points, faces), points[faces]
            low, high = points.min(0), points.max(0)
            pairs = self_pairs(bvh, faces, topology(obj, faces)[1])
            bone_lengths = {}
            for bone, lower, upper, bone_triangles, bone_bvh in bones:
                if (lower > high).any() or (low > upper).any():
                    continue
                hits = np.asarray(bvh.overlap(bone_bvh), dtype=np.int32).reshape(-1, 2)
                if hits.size:
                    bone_lengths[bone] = intersection_length(triangles[hits[:, 0]], bone_triangles[hits[:, 1]])
            frame[label] = {
                "bone_intersection_segment_length_m": bone_lengths,
                "self_intersection_segment_length_m": intersection_length(triangles[pairs[:, 0]],
                                                                         triangles[pairs[:, 1]]),
            }
        rows.append({"source_index": record["source_index"], "state_sha256": record["state_sha256"], "surfaces": frame})
    return {"run_id": expected["run_id"],
            "limitations": "Sum of noncoplanar triangle intersection segment lengths; not penetration depth or volume.",
            "frames": rows}


if __name__ == "__main__":
    output, mapping, repair = map(Path, sys.argv[sys.argv.index("--") + 1:])
    labels = json.loads(repair.read_text())["audited_surfaces"]
    output.write_text(json.dumps(measure(bpy.context.scene, json.loads(mapping.read_text()), labels), indent=2))
