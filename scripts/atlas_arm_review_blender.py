"""Inspect saved upper-limb volume, path and bone geometry in Blender."""

import json
from pathlib import Path
import re
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_collision_blender import ATLAS, bone_surfaces, intersections, rendered_meshes, surface, tree


ARM_PATHS = {
    "long head of {side} biceps brachii": "BIClong",
    "short head of {side} biceps brachii": "BICshort",
    "long head of {side} triceps brachii": "TRIlong",
    "lateral head of {side} triceps brachii": "TRIlat",
    "medial head of {side} triceps brachii": "TRImed",
    "{side} brachialis": "BRA",
    "{side} brachioradialis": "BRD",
    "{side} extensor indicis": "EIP",
}
ARM_BONES = {name + suffix for name in ("humerus", "ulna", "radius") for suffix in ("", "_mirror")}


def path_muscles(scene):
    available = {}
    for obj in rendered_meshes(scene.collection.children[ATLAS]):
        label = obj.get("source_label", "").split(" [", 1)[0].lower()
        available[label] = obj
    return {
        code + "_" + side[0]: available[pattern.format(side=side)]
        for side in ("right", "left")
        for pattern, code in ARM_PATHS.items()
    }


def endpoint_distances(mesh_tree, points):
    values = [mesh_tree.find_nearest(Vector(point))[3] for point in points]
    if any(value is None or not np.isfinite(value) for value in values):
        raise ValueError("could not evaluate path endpoint distance")
    return values


def check_arm_bone_pose(record, graph):
    recorded = {g["name"]: g for g in record["geoms"] if g["name"] in ARM_BONES}
    if set(recorded) != ARM_BONES:
        raise ValueError("saved arm landmark geometry is incomplete")
    for geom in recorded.values():
        bone = bpy.data.objects["Mesh_" + geom["usd_name"]].evaluated_get(graph)
        if (bone.matrix_world.translation - Vector(geom["position_m"])).length > 2e-6:
            raise ValueError("upper-limb scene does not match saved bone poses")


def audit(scene, expected):
    meshes = path_muscles(scene)
    result = []
    if [frame["frame"] for frame in expected["frames"]] != list(range(scene.frame_end + 1)):
        raise ValueError("review inputs do not describe this Blender timeline")
    for record in expected["frames"]:
        scene.frame_set(record["frame"])
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        check_arm_bone_pose(record, graph)
        bones = bone_surfaces(scene.collection.children["bones"].objects, graph)
        rows = {}
        for native, obj in meshes.items():
            segments = sorted((p for p in record["paths"] if p["actuator"] == native),
                              key=lambda p: p["segment"])
            if not segments or any(p["segment"] != i for i, p in enumerate(segments)):
                raise ValueError(f"invalid native path sample: {native}")
            start, end = segments[0]["start_m"], segments[-1]["end_m"]
            points, triangles = surface(obj, graph)
            rows[native] = {
                "source_mesh": obj["source_label"],
                "native_path_endpoints_m": [start, end],
                "nearest_mesh_distance_m": endpoint_distances(tree(points, triangles), [start, end]),
                "bone_triangle_crossing_pairs": intersections(points, triangles, bones),
                "native_path_segment_count": len(segments),
            }
        result.append({"frame": record["frame"], "source_index": record["source_index"],
                       "time_s": record["time_s"], "muscles": rows,
                       "palm_pad_floor_clearance_m": {p["name"]: p["position_m"][2] - p["radius_m"]
                                                      for p in record["hand_pads"]},
                       "hand_vertical_force_N": {h["side"]: h["force_world_N"][2] for h in record["hands"]}})
    return {"scope": "bilateral selected upper-limb meshes", "source_run_id": expected["run_id"],
            "limitation": "Distances are to model path endpoints and estimate a display mismatch. They do not measure anatomical attachment footprints.",
            "frames": result}


def render_review(scene, expected, output, motion=False, elbows=False, elbow_phases=False):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    if not any(device.type == "OPTIX" for device in prefs.devices):
        raise RuntimeError("OptiX device required for the upper-limb review")
    for device in prefs.devices:
        device.use = device.type == "OPTIX"
    scene.cycles.device = "GPU"
    scene.render.image_settings.file_format = "PNG"
    if motion:
        if elbow_phases:
            scene.render.resolution_x, scene.render.resolution_y = 1280, 720
            scene.cycles.samples = 12
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            scene.render.filepath = str(output / f"motion-{frame:03d}.png")
            bpy.ops.render.render(write_still=True)
    scene.render.resolution_x, scene.render.resolution_y = 820, 660
    scene.cycles.samples = 8
    camera = scene.camera
    camera.data.type = "ORTHO"
    if elbows:
        bottom = scene.frame_end // 2
        indices = [0, bottom, scene.frame_end] if elbow_phases else [bottom]
        for index in indices:
            scene.frame_set(index)
            axes = {row["joint"]: row["origin_m"] for row in expected["frames"][index]["joint_axes"]}
            for side, sign in (("r", -1), ("l", 1)):
                target = Vector(axes["elbow_flexion_" + side])
                offset = Vector((.22, sign * 2.3, .32))
                camera.data.ortho_scale = .43
                camera.location = target + offset
                camera.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
                suffix = "" if index == bottom else f"-{index:03d}"
                scene.render.filepath = str(output / f"elbow-{side}{suffix}.png")
                bpy.ops.render.render(write_still=True)
        return
    phases = {"start": 0, "bottom": scene.frame_end // 2, "return": scene.frame_end}
    for phase, index in phases.items():
        scene.frame_set(index)
        geom = {g["name"]: Vector(g["position_m"]) for g in expected["frames"][index]["geoms"]}
        wrist = geom["radius"]
        fingers = [xyz for name, xyz in geom.items() if re.match(r"hand_detail_r_.*(?:proxph|thumbprox)$", name)]
        if not fingers:
            raise ValueError("no right-hand distal focus geoms")
        palm = sum(fingers, Vector()) / len(fingers)
        arm = (2 * geom["humerus"] + wrist + palm) / 4
        for label, center, offset, width in (
            ("arm", arm, Vector((.2, -2.65, .42)), .91),
            ("hand", (wrist + 2 * palm) / 3, Vector((.18, -1.35, .92)), .35),
        ):
            camera.data.ortho_scale = width
            camera.location = center + offset
            camera.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(output / f"{label}-{phase}.png")
            bpy.ops.render.render(write_still=True)
            if label == "hand" and phase == "bottom" and motion:
                layer = scene.collection.children["hand_contacts"]
                layer.hide_render = False
                for obj in list(layer.objects):
                    obj.hide_render = not obj.name.startswith("mechanical_pad_")
                scene.render.filepath = str(output / "hand-contact-bottom.png")
                bpy.ops.render.render(write_still=True)
                layer.hide_render = True


if __name__ == "__main__":
    directory, mapping, *mode = sys.argv[sys.argv.index("--") + 1:]
    path = Path(directory)
    expected = json.loads(Path(mapping).read_text())
    if mode in (["images"], ["motion"], ["elbows"], ["seam-motion"], ["arm-motion"]):
        render_review(bpy.context.scene, expected, path, motion=mode in (["motion"], ["seam-motion"], ["arm-motion"]),
                      elbows=mode in (["elbows"], ["seam-motion"], ["arm-motion"]), elbow_phases=mode == ["arm-motion"])
    else:
        (path / "arm-audit.json").write_text(json.dumps(audit(bpy.context.scene, expected), indent=2))
