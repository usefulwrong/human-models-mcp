"""Compare fixed-frame shoulder variants against the same native bone triangles."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_arm_surface_blender import self_check, self_pairs
from atlas_collision_blender import intersections, surface, tree


def measure(points, faces, weld, bones, sites):
    bvh = tree(points, faces)
    bone_pairs = intersections(points, faces, bones)
    return {
        "vertices": len(points),
        "triangles": len(faces),
        "bone_triangle_crossing_pairs": {name: bone_pairs.get(name, 0) for name, *_ in bones},
        "nonadjacent_surface_self_pairs": len(self_pairs(bvh, faces, weld)),
        "attachment_site_to_surface_m": {name: bvh.find_nearest(Vector(point))[3] for name, point in sites.items()},
        "minimum_height_m": float(points[:, 2].min()),
        "plane_crossing_triangles": int(np.count_nonzero(
            (points[faces, 2].min(1) <= 0) & (points[faces, 2].max(1) >= 0))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qa_input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--author-weights", type=Path, nargs=2, metavar=("EXPECTED_JSON", "SCENE_BLEND"))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    payload = json.loads(args.qa_input.read_text())
    self_check()
    tris = np.asarray(payload["surface_faces"], dtype=np.int32)
    author_frames, author_object, author_info = {}, None, None
    if args.author_weights:
        expected_file, blend_file = args.author_weights
        expected = json.loads(expected_file.read_text())
        author_frames = {frame["source_index"]: frame for frame in expected["frames"]}
        bpy.ops.wm.open_mainfile(filepath=str(blend_file), load_ui=False)
        author_object, = (
            obj for obj in bpy.context.scene.objects
            if obj.type == "MESH" and obj.get("source_label") == "Clavicular part of right pectoralis major [FJ1447]"
        )
        armature, = (modifier.object for modifier in author_object.modifiers if modifier.type == "ARMATURE")
        if armature is None:
            raise ValueError("historical muscle surface has no authored rig")
        memberships = Counter(author_object.vertex_groups[group.group].name
                              for vertex in author_object.data.vertices
                              for group in vertex.groups if group.weight > 0)
        author_info = {
            "prior_run_id": expected["run_id"], "scene_sha256": hashlib.sha256(blend_file.read_bytes()).hexdigest(),
            "object": author_object["source_label"], "armature": armature.name,
            "nonzero_authored_vertex_memberships": dict(memberships),
            "role": "matched-state, different-mesh exploratory control",
        }
    result = []
    for frame in payload["frames"]:
        bones = []
        for name, mesh in frame["native_bones"].items():
            vertices, faces = np.asarray(mesh["vertices_m"]), np.asarray(mesh["faces"])
            bones.append((name, vertices.min(axis=0), vertices.max(axis=0), tree(vertices, faces)))
        sites = frame["attachment_sites_m"]
        metrics = frame["variants"]
        for name, vertices in frame["variant_vertices_m"].items():
            points = np.asarray(vertices)
            _, weld = np.unique(points, axis=0, return_inverse=True)
            metrics[name].update(measure(points, tris, weld, bones, sites))
        if author_object is not None:
            prior = author_frames[frame["state_index"]]
            if (prior["time_s"], prior["state_sha256"]) != (frame["frame_time"], frame["state_sha256"]):
                raise ValueError("author-weight control sampled a different MuJoCo state")
            bpy.context.scene.frame_set(prior["frame"])
            bpy.context.view_layer.update()
            points, faces = surface(author_object, bpy.context.evaluated_depsgraph_get())
            _, weld = np.unique(points, axis=0, return_inverse=True)
            metrics["historical_myo_author_weights"] = measure(points, faces, weld, bones, sites)
        result.append({key: frame[key] for key in ("state_index", "frame_time", "state_sha256", "phase",
                                                   "native_path_observations", "variants")})
    with args.output.open("x") as stream:
        json.dump({"rigid_fit_controls": payload["rigid_fit_controls"], "author_control": author_info,
                   "frames": result}, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
