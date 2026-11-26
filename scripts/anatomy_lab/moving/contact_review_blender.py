"""Audit the evaluated Blender scene and render source-indexed contact close-ups."""

import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contact_audit import triangle_metrics  # noqa: E402


def geometry(obj, graph):
    actual = obj.evaluated_get(graph)
    mesh = actual.data
    points = np.empty(3 * len(mesh.vertices), dtype=np.float32)
    mesh.vertices.foreach_get("co", points)
    matrix = np.array(actual.matrix_world)
    return points.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]


def triangles(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    indices = np.empty(3 * len(mesh.loop_triangles), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", indices)
    return indices.reshape(-1, 3)


def audit(scene, motion, output):
    floor = scene.objects["World floor"]
    meshes = [(obj, triangles(obj)) for obj in scene.objects if obj.type == "MESH"
              and not obj.hide_render and obj.get("layer") in ("SKELETON", "MUSCLES")]
    frames = []
    for frame in motion["frames"]:
        index = frame["state_index"]
        for between in (0, .25, .5, .75) if index < len(motion["frames"]) - 1 else (0,):
            scene.frame_set(index, subframe=between)
            graph = bpy.context.evaluated_depsgraph_get()
            origin, b, c = geometry(floor, graph)[:3]
            normal = np.cross(b - origin, c - origin)
            normal *= np.sign(normal[2]) / np.linalg.norm(normal)
            signed_floor_z = float(origin[2])
            metrics = {}
            for obj, faces in meshes:
                points = geometry(obj, graph)
                dist = (points - origin) @ normal
                value = triangle_metrics(dist, faces)
                if value["max_depth_m"] or obj.name.startswith(("hand_detail_", "r_bofoot", "l_bofoot")):
                    metrics[obj.name] = value
            frames.append({"index": index, "subframe": between, "state_sha256": frame["state_sha256"],
                           "floor_z_m": signed_floor_z, "normal": normal.tolist(), "surfaces": metrics})
    (output / "surface-audit.json").write_text(json.dumps({"run_id": motion["run_id"],
        "trajectory_sha256": scene["trajectory_sha256"], "meshes_checked": [obj.name for obj, _ in meshes],
        "unavailable_layers": {"SKIN": "UNMEASURABLE"},
        "frames": frames}, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def render(scene, motion, output, backend):
    debug = backend.endswith("_DEBUG")
    backend = backend.removesuffix("_DEBUG")
    if debug:
        bpy.data.collections["OVERLAYS"].hide_render = False
        bpy.context.view_layer.layer_collection.children["OVERLAYS"].hide_viewport = False
    prefix = backend.lower() + ("-debug" if debug else "")
    scene.render.engine = "CYCLES"
    devices = []
    if backend == "CPU":
        scene.cycles.device = "CPU"
    else:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = backend
        prefs.refresh_devices()
        for device in prefs.devices:
            device.use = device.type == backend
            if device.use:
                devices.append(device.name)
        assert devices, f"no {backend} device"
        scene.cycles.device = "GPU"
    print("CYCLES", backend, devices, bpy.app.version_string, flush=True)
    scene.render.resolution_x, scene.render.resolution_y = 720, 440
    scene.render.resolution_percentage = 100
    scene.cycles.samples = 8
    center_camera = scene.camera
    camera_data = bpy.data.cameras.new("Contact close-up")
    camera_data.clip_start = .003
    camera_data.lens = 42
    camera = bpy.data.objects.new("Contact close-up", camera_data)
    scene.collection.objects.link(camera)
    main = [(f["phase"], f["state_index"], None, None) for f in motion["frames"] if f["phase"] != "motion"]
    if backend == "OPTIX":
        # Close-ups are centered on actual objects even when the trial has drifted.
        views = {"side": (0, -.31, .028), "front": (.31, 0, .028),
                 "underside": (.13, -.17, -.13), "oblique": (.19, -.21, .115)}
        bottom = main[1][1]
        samples = {"right-thumb": "hand_detail_r_thumbdist", "left-thumb": "hand_detail_l_thumbdist",
                   "right-toe": "r_bofoot", "left-toe": "l_bofoot"}
        for label, name in samples.items():
            for view, offset in views.items():
                main.append((f"{label}-{view}", bottom, name, offset))
        if motion["run_id"] == "4c510b1a-70da-4b7d-b51e-ba7fad0ecf82":
            main += [(f"right-thumb-side-{i}", i, samples["right-thumb"], views["side"])
                     for i in (10, 27, 45, 65, 72, 90)]
    if debug:
        main = [shot for shot in main if shot[0] == "bottom" or shot[0].endswith("oblique")]
    floor = scene.objects["World floor"]
    rows = []
    for label, index, name, offset in main:
        scene.frame_set(index)
        floor.hide_render = False
        scene.camera = center_camera
        if name:
            graph = bpy.context.evaluated_depsgraph_get()
            target = Vector(geometry(scene.objects[name], graph).mean(axis=0))
            camera.location = target + Vector(offset)
            camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.camera = camera
            floor.hide_render = "underside" in label
        path = output / f"{prefix}-{label}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        rows.append({"label": label, "index": index, "frame": motion["frames"][index],
                     "display_floor_hidden": bool(floor.hide_render),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (output / f"{prefix}-renders.json").write_text(json.dumps({"devices": devices, "backend": backend,
        "version": bpy.app.version_string, "run_id": motion["run_id"], "frames": rows}, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    clip, output, mode = sys.argv[sys.argv.index("--") + 1:]
    motion = json.loads((Path(clip) / "motion.json").read_text(encoding="utf-8"))
    scene = bpy.context.scene
    assert scene["trajectory_sha256"] == motion["trajectory_sha256"]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if mode == "audit":
        audit(scene, motion, output)
    else:
        render(scene, motion, output, mode)
