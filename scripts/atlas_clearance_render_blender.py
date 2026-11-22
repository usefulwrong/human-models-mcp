"""Render the clearance scene and matching close-ups for visual review."""

from pathlib import Path
import sys

import bpy
from mathutils import Vector

from atlas_torso_views_blender import camera_pose


def render(scene, output, prefix, video):
    scene.render.image_settings.file_format = "PNG"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    if not any(device.type == "OPTIX" for device in prefs.devices):
        raise RuntimeError("OptiX device required for this recipe")
    for device in prefs.devices:
        device.use = device.type == "OPTIX"
    scene.cycles.device = "GPU"
    if video:
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            scene.render.filepath = str(output / f"motion-{frame:03d}.png")
            bpy.ops.render.render(write_still=True)

    # The chest inspection camera is below the support plane, outside the simulated volume.
    bpy.data.objects["Mesh_floor_id0_geom"].hide_render = True
    scene.render.resolution_x, scene.render.resolution_y = 680, 810
    scene.cycles.samples = 8
    camera = scene.camera
    camera.data.ortho_scale = .89
    light = bpy.data.lights.new("Anterior inspection softbox", "AREA")
    light.energy, light.size = 100, 1.5
    lamp = bpy.data.objects.new(light.name, light)
    scene.collection.objects.link(lamp)
    track = [("start", scene.frame_start), ("bottom", scene.frame_end // 2), ("return", scene.frame_end)]
    for label, frame in track:
        scene.frame_set(frame)
        center = Vector((1.14, 0, .35))
        camera_pose(camera, center, Vector((1, 0, 0)), (.08, -.75, -2.6))
        lamp.location = center + Vector((.25, -.42, -1.35))
        lamp.rotation_euler = (center - lamp.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(output / f"{prefix}-{label}.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    directory, prefix, *mode = sys.argv[sys.argv.index("--") + 1:]
    render(bpy.context.scene, Path(directory), prefix, video=mode == ["video"])
