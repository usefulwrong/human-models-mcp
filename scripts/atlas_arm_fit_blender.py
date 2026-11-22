"""Refit the distal brachioradialis surfaces against the native radius path endpoints."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_arm_review_blender import audit, path_muscles
from atlas_clearance_blender import bake_surface
from atlas_collision_blender import ATLAS, check_detector, surface, tree


SUPPORT_M = .038
FRACTION = .75
MAX_SHIFT_M = .011


def main(output, expected):
    check_detector()
    scene = bpy.context.scene
    before = audit(scene, expected)
    paths = ("BRD_r", "BRD_l")
    meshes = path_muscles(scene)
    frames = list(range(scene.frame_end + 1))
    poses = {name: [] for name in paths}
    peak_shift = 0.
    for index in frames:
        scene.frame_set(index)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        for name in paths:
            points, faces = surface(meshes[name], graph)
            proximal, distal = before["frames"][index]["muscles"][name]["native_path_endpoints_m"]
            nearest, _, _, distance = tree(points, faces).find_nearest(Vector(distal))
            if distance is None or distance * FRACTION > MAX_SHIFT_M:
                raise ValueError(f"distal fit exceeds allowed displacement: {name}, frame {index}")
            offset = FRACTION * (np.asarray(distal) - np.asarray(nearest))
            distance = np.linalg.norm(points - np.asarray(nearest), axis=1)
            weight = (1 - distance / SUPPORT_M).clip(0, 1)
            displacement = (weight ** 2 * (3 - 2 * weight))[:, None] * offset
            if np.linalg.norm(np.asarray(proximal) - np.asarray(nearest)) <= 2 * SUPPORT_M:
                raise ValueError("distal fit region overlaps the proximal landmark")
            peak_shift = max(peak_shift, float(np.linalg.norm(displacement, axis=1).max()))
            poses[name].append((points + displacement).astype(np.float32))
    atlas = scene.collection.children[ATLAS]
    fitted = bpy.data.collections.new("Forearm · distal landmark fit")
    archive = bpy.data.collections.new("Forearm originals · retained for comparison")
    atlas.children.link(fitted)
    atlas.children.link(archive)
    for name in paths:
        obj = meshes[name]
        revised = bake_surface(obj, fitted, frames, poses[name])
        revised["correction"] = "Local distal geometric fit to native brachioradialis path"
        for group in list(obj.users_collection):
            group.objects.unlink(obj)
        archive.objects.link(obj)
    archive.hide_render = True
    bpy.context.view_layer.layer_collection.children[ATLAS].children[archive.name].hide_viewport = True
    after = audit(scene, expected)
    checks = []
    failures = []
    for old, new in zip(before["frames"], after["frames"], strict=True):
        for name in paths:
            a, b = (frame["muscles"][name] for frame in (old, new))
            old_gap, new_gap = (row["nearest_mesh_distance_m"][1] for row in (a, b))
            old_crossings, new_crossings = (sum(row["bone_triangle_crossing_pairs"].values()) for row in (a, b))
            if new_gap >= old_gap or new_crossings > old_crossings:
                failures.append({"source_index": old["source_index"], "native_path": name})
            if abs(a["nearest_mesh_distance_m"][0] - b["nearest_mesh_distance_m"][0]) > 1e-6:
                failures.append({"source_index": old["source_index"], "native_path": name, "proximal_changed": True})
            checks.append({"source_index": old["source_index"], "native_path": name,
                           "distal_gap_before_m": old_gap, "distal_gap_after_m": new_gap,
                           "crossings_before": old_crossings, "crossings_after": new_crossings})
    (output / "arm-fit.json").write_text(json.dumps({
        "status": "REJECTED" if failures else "ILLUSTRATIVE_DISTAL_FIT",
        "scope": "bilateral brachioradialis",
        "support_radius_m": SUPPORT_M,
        "maximum_vertex_displacement_m": peak_shift,
        "frames": checks,
        "failures": failures,
        "limitation": "Model path endpoints guide a local mesh adjustment. The anatomical footprint and surrounding tissues remain unvalidated.",
    }, indent=2))
    if failures:
        raise ValueError("distal fit failed path or bone crossing comparison")
    scene.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "arm-fit.blend"), compress=True)


if __name__ == "__main__":
    destination, mapping = sys.argv[sys.argv.index("--") + 1:]
    main(Path(destination), json.loads(Path(mapping).read_text()))
