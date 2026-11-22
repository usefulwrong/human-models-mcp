"""Render the textured moving atlas and a synchronized rectus abdominis dissection."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_collision_blender import ATLAS, RECTUS, rendered_meshes
from atlas_torso_views_blender import camera_pose
from muscle_materials import SOURCE_TENDON, apply, set_source_tendon_mask


def restore_rectus_masks(collection, source):
    names = ["atlas-source-rectus-r", "atlas-source-rectus-l"]
    with bpy.data.libraries.load(str(source), link=False) as (available, imported):
        if not set(names).issubset(available.objects):
            raise ValueError("pinned rectus source does not contain both sides")
        imported.objects = names
    source_meshes = {obj["source_object"]: obj.data for obj in imported.objects}
    for obj in collection.objects:
        target = obj.data
        original = source_meshes[obj["source_object"]]
        original_loops = np.empty(len(original.loops), dtype=np.int32)
        target_loops = np.empty(len(target.loops), dtype=np.int32)
        original.loops.foreach_get("vertex_index", original_loops)
        target.loops.foreach_get("vertex_index", target_loops)
        if (len(original.vertices) != len(target.vertices) or len(original.polygons) != len(target.polygons)
            or not np.array_equal(original_loops, target_loops)):
            raise ValueError("rectus topology differs from source tendon face assignments")
        mask = np.empty(len(original.polygons), dtype=np.bool_)
        original.attributes[SOURCE_TENDON].data.foreach_get("value", mask)
        if np.count_nonzero(mask) != 6611:
            raise ValueError("unexpected number of source tendon faces")
        set_source_tendon_mask(target, mask)


def press_view(scene):
    groups = scene.collection.children
    groups[ATLAS].hide_render = True
    bones = ("Rib", "thoracic", "lumbar", "sacrum", "pelvis", "sternum", "Sternum")
    for obj in list(groups["bones"].objects):
        obj.hide_render = not any(term in obj.name for term in bones)
    bpy.data.objects["Mesh_floor_id0_geom"].hide_render = True
    scene.render.resolution_x, scene.render.resolution_y = 680, 810
    scene.camera.data.ortho_scale = .70
    center = Vector((1.03, 0, .32))
    camera_pose(scene.camera, center, Vector((1, 0, 0)), (.02, -.28, -2.6))
    light = bpy.data.lights.new("Rectus inspection softbox", "AREA")
    light.energy, light.size = 95, 1.25
    lamp = bpy.data.objects.new(light.name, light)
    scene.collection.objects.link(lamp)
    lamp.location = center + Vector((.28, -.32, -1.13))
    lamp.rotation_euler = (center - lamp.location).to_track_quat("-Z", "Y").to_euler()


def render(scene, frames, output, prefix):
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = str(output / f"{prefix}-{frame:03d}.png")
        bpy.ops.render.render(write_still=True)


def main(output, source, preview):
    scene = bpy.context.scene
    groups = scene.collection.children
    scene.frame_set(scene.frame_start)
    restore_rectus_masks(groups[RECTUS], source)
    textured = set()
    for obj in groups[ATLAS].all_objects:
        if obj.type == "MESH" and obj.data not in textured:
            apply(obj.data)
            textured.add(obj.data)
    tendon_faces = {obj["source_object"]: apply(obj.data, "local_z") for obj in groups[RECTUS].objects}
    if sorted(tendon_faces.values()) != [6611, 6611]:
        raise ValueError("expected both rectus meshes with preserved source tendon faces")
    visible_atlas = len(list(rendered_meshes(groups[ATLAS])))
    if visible_atlas != 288:
        raise ValueError("expected complete current MyoSuite display layer")
    bpy.data.texts.new("Atlas materials · evidence").write(
        "Procedural illustration in fixed mesh coordinates. The dominant shape axis of the atlas "
        "surfaces supplies a display direction. The rectus uses its registered longitudinal axis "
        "and the source Z-Anatomy face assignment. No imaging-derived fibre or strain field."
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "atlas-textured.blend"), compress=True)
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    devices = [device.name for device in prefs.devices if device.type == "OPTIX"]
    if not devices:
        raise RuntimeError("OptiX device required for the paired render")
    for device in prefs.devices:
        device.use = device.type == "OPTIX"
    scene.cycles.device = "GPU"
    scene.render.image_settings.file_format = "PNG"
    frames = [scene.frame_end // 2] if preview else list(range(scene.frame_start, scene.frame_end + 1))
    scene.cycles.samples = 8 if preview else 6
    render(scene, frames, output, "atlas")
    press_view(scene)
    render(scene, frames, output, "press")
    (output / "materials.json").write_text(json.dumps({
        "level": "illustrative_display_material",
        "visible_atlas_meshes_textured": visible_atlas,
        "visible_rectus_meshes_textured": len(tendon_faces),
        "rectus_tendon_faces_from_source": tendon_faces,
        "rectus_source": "Z-Anatomy CC BY-SA 4.0",
        "geometry_generation": "none; stored local material coordinates and shader only",
        "display_direction": "rectus longitudinal axis and dominant mesh direction for other volumes",
        "source_times": "identical saved states in both views",
        "rendered_frames": frames,
        "backend": "optix",
        "devices": devices,
    }, indent=2))


if __name__ == "__main__":
    directory, source, *mode = sys.argv[sys.argv.index("--") + 1:]
    main(Path(directory), Path(source), preview=mode == ["preview"])
