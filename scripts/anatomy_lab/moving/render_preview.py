"""Render exact saved frames from a verified editable MotionScene."""

import argparse
import json
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", choices=("CPU", "CUDA", "OPTIX"), default="CPU")
    parser.add_argument("--phases-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    scene = bpy.context.scene
    notes = bpy.data.texts["MotionScene evidence and attribution"].as_string()
    evidence = json.loads(notes[notes.index("{"):])
    assert scene.frame_end + 1 == len(evidence["frames"])
    assert [f["state_index"] for f in evidence["frames"]] == list(range(scene.frame_end + 1))
    assert all(abs(f["frame_time"] - f["state_index"] / scene.render.fps) < 1e-8 for f in evidence["frames"])
    scene.camera = bpy.data.objects["Research side"]
    scene.render.resolution_x, scene.render.resolution_y = 960, 600
    scene.render.resolution_percentage = 100
    scene.cycles.samples = 8
    scene.cycles.device = "CPU"
    if args.device != "CPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = args.device
        prefs.refresh_devices()
        for device in prefs.devices:
            device.use = device.type == args.device
        devices = [device.name for device in prefs.devices if device.use]
        if not devices:
            raise RuntimeError(f"No Cycles {args.device} device")
        print(f"Cycles {args.device} devices: {devices}", flush=True)
        scene.cycles.device = "GPU"
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.13, .22, .28, 1)
    for name, color, power in (
        ("Soft key", (.83, .93, 1), 205),
        ("Warm rim", (1, .69, .45), 190),
        ("Head fill", (.92, 1, .96), 60),
    ):
        light = bpy.data.lights[name]
        light.color = color
        light.energy = power
    args.output.mkdir(parents=True, exist_ok=True)
    frames = [f for f in evidence["frames"] if not args.phases_only or f["phase"] != "motion"]
    for frame in frames:
        scene.frame_set(frame["state_index"])
        scene.render.filepath = str(args.output / f"frame-{scene.frame_current:03d}.png")
        bpy.ops.render.render(write_still=True)
    (args.output / "render.json").write_text(json.dumps({
        "scene_version": "research-preview/1", "device": args.device, "blender": bpy.app.version_string,
        "run_id": evidence["run_id"], "source_motion_sha256": scene["motion_sha256"],
        "trajectory_sha256": scene["trajectory_sha256"], "frames": frames,
        "camera": {"name": scene.camera.name, "matrix_world": [list(row) for row in scene.camera.matrix_world],
                   "vertical_fov_rad": scene.camera.data.angle_y, "size_px": [960, 600]},
    }, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
