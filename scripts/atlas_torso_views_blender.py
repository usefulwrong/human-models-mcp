"""Organize the experimental torso meshes and render two isolated inspection views."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


TRUNK = {
    "Chest · atlas volumes": ("pectoralis ", "serratus anterior", "subclavius", "intercostal"),
    "Abdomen · external obliques": ("external oblique",),
    "Back · atlas volumes": (
        "trapezius", "rhomboid", "iliocostalis", "longissimus", "rotator", "spinalis",
        "interspinal", "intertransvers", "serratus posterior",
    ),
}


def group_torso(collection):
    by_region = {}
    for name, terms in TRUNK.items():
        group = bpy.data.collections.new(name)
        collection.children.link(group)
        by_region[name] = group
        for obj in list(collection.objects):
            if any(term in obj.get("source_label", "").lower() for term in terms):
                group.objects.link(obj)
                collection.objects.unlink(obj)
        if not group.objects:
            raise ValueError(f"empty atlas torso group: {name}")
    return by_region


def camera_pose(camera, target, body_axis, offset):
    camera.location = target + Vector(offset)
    backward = (camera.location - target).normalized()
    up = (body_axis - backward * body_axis.dot(backward)).normalized()
    right = up.cross(backward)
    camera.rotation_euler = Matrix((right, up, backward)).transposed().to_euler()


def main(out):
    scene = bpy.context.scene
    groups = scene.collection.children
    atlas = groups["Candidate mesh transfer · engineering probe"]
    rectus = groups["Rectus abdominis · Z-Anatomy"]
    bones = groups["bones"]
    torso = group_torso(atlas)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "torso.blend"), compress=True)

    camera = scene.camera
    camera.data.ortho_scale = .78
    scene.render.resolution_x, scene.render.resolution_y = 640, 820
    scene.cycles.samples = 8
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    assert any(device.type == "OPTIX" for device in prefs.devices)
    for device in prefs.devices:
        device.use = device.type == "OPTIX"
    scene.cycles.device = "GPU"
    for obj in list(atlas.all_objects):
        if obj.type == "MESH":
            obj.hide_render = True
    keep_bones = ("Rib", "thoracic", "lumbar", "sacrum", "pelvis", "cerv", "sternum", "Sternum", "clavicle", "scapula")
    for obj in list(bones.objects):
        obj.hide_render = not any(term in obj.name for term in keep_bones)
    bpy.data.objects["Mesh_floor_id0_geom"].hide_render = True
    light = bpy.data.lights.new("Torso inspection softbox", "AREA")
    light.energy, light.size = 140, 1.3
    lamp = bpy.data.objects.new(light.name, light)
    scene.collection.objects.link(lamp)
    scene.render.image_settings.file_format = "PNG"
    track = [("start", 0), ("bottom", scene.frame_end // 2), ("return", scene.frame_end)]
    for name, direction in (("press", -1), ("back-detail", 1)):
        rectus.hide_render = direction > 0
        if direction > 0:
            for obj in list(torso["Back · atlas volumes"].objects):
                obj.hide_render = False
        for phase, frame in track:
            scene.frame_set(frame)
            body_axis = Vector((1, 0, 0))
            center = Vector((1.03, 0, .40 if direction > 0 else .29))
            camera_pose(camera, center, body_axis, (0, -.14, 2.8 * direction))
            lamp.location = center + Vector((.28, -.32, 1.13 * direction))
            lamp.rotation_euler = (center - lamp.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(out / f"{name}-{phase}.png")
            bpy.ops.render.render(write_still=True)
    (out / "torso-layers.json").write_text(json.dumps({
        "mesh_counts": {name: len(group.objects) for name, group in torso.items()},
        "rectus_mesh_count": len(rectus.objects),
        "inspection_frame_indices": dict(track),
    }, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[sys.argv.index("--") + 1]))
