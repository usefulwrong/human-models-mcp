"""Build an offline reference scene from the source pose and authored armature."""

import json
from pathlib import Path
import re
import runpy
import struct
import sys

import bpy
from mathutils import Vector

DEVICE, SOURCE_URL, SOURCE_SHA256 = sys.argv[sys.argv.index("--") + 1:]
OUT = Path("/atlas-output")


def source_names():
    with Path("/atlas.glb").open("rb") as stream:
        stream.read(12)
        size, kind = struct.unpack("<I4s", stream.read(8))
        if kind != b"JSON" or not 0 < size <= 2_000_000:
            raise ValueError("invalid pinned GLB metadata")
        meshes = json.loads(stream.read(size))["meshes"]
    # Blender caps ID names at 63 bytes. The pinned ASCII labels have unique prefixes.
    names = {mesh["name"][:63]: mesh["name"] for mesh in meshes}
    if len(meshes) != 416 or len(names) != len(meshes):
        raise ValueError("pinned atlas mesh names differ or collide after import")
    return names


def aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def inspect_meshes():
    names = source_names()
    apply_material = runpy.run_path("/muscle-materials.py")["apply"]
    source_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.data.name in names]
    if {obj.data.name for obj in source_objects} != names.keys() or len(source_objects) != len(names):
        raise ValueError("pinned atlas mesh count differs")
    rows, shown = [], []
    for obj in sorted(source_objects, key=lambda value: value.data.name):
        label = names[obj.data.name]
        match = re.search(r"\[(FJ\d+M?)\]$", label)
        if not match:
            raise ValueError(f"missing BodyParts3D identifier for {label}")
        rig = obj.find_armature()
        if rig is None or not obj.data.vertices:
            raise ValueError(f"missing authored rig or geometry for {label}")
        weights = {}
        for vertex in obj.data.vertices:
            for group in vertex.groups:
                if group.weight > 0:
                    bone = obj.vertex_groups[group.group].name
                    if bone not in rig.data.bones:
                        raise ValueError(f"weight for unknown bone {bone} on {label}")
                    weights[bone] = weights.get(bone, 0) + 1
        if not weights:
            raise ValueError(f"no positive authored bone weights for {label}")
        # The source portfolio is broader than skeletal muscle. Hide obvious cardiac entries
        # and leave the rest explicitly unclassified until an anatomical inventory is reviewed.
        cardiac = "papillary muscle" in label.lower() and "ventricle" in label.lower()
        obj.name = label
        obj["source_label"] = label
        obj["bodyparts3d_id"] = match[1]
        obj["review_status"] = "excluded_cardiac" if cardiac else "source_geometry_unreviewed"
        obj.hide_render = cardiac
        obj.hide_set(cardiac)
        apply_material(obj.data)
        obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
        if not cardiac:
            shown.append(obj)
        rows.append({"name": label, "bodyparts3d_id": match[1], "vertices": len(obj.data.vertices),
                     "authored_bone_weights": weights, "review_status": obj["review_status"]})
    return shown, rows


def render_views(scene, shown):
    points = [obj.matrix_world @ Vector(p) for obj in shown for p in obj.bound_box]
    lower = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    upper = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    if not 1.3 <= upper.z - lower.z <= 2.2:
        raise ValueError("source atlas is not an upright metre-scale reference")
    center = (lower + upper) / 2
    chest = [p for obj in shown if "sternocostal part" in obj.name.lower() and "pectoralis major" in obj.name.lower()
             for p in [obj.matrix_world @ (sum(map(Vector, obj.bound_box), Vector()) / 8)]]
    back = [p for obj in shown if "trapezius" in obj.name.lower()
            for p in [obj.matrix_world @ (sum(map(Vector, obj.bound_box), Vector()) / 8)]]
    if len(chest) != 2 or not back:
        raise ValueError("missing source anterior or posterior landmarks")
    anterior = sum(p.y for p in chest) / len(chest) - sum(p.y for p in back) / len(back)
    if abs(anterior) < .05:
        raise ValueError("cannot distinguish anterior and posterior camera directions")
    direction = 1 if anterior > 0 else -1

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 800
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world = bpy.data.worlds.new("Atlas reference world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.24, .26, .31, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = .55
    chosen = ["CPU"]
    if DEVICE == "gpu":
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "OPTIX"
        preferences.refresh_devices()
        chosen = [device.name for device in preferences.devices if device.type == "OPTIX"]
        if not chosen:
            raise RuntimeError("no OptiX GPU available")
        for device in preferences.devices:
            device.use = device.type == "OPTIX"
        scene.cycles.device = "GPU"
    studio = bpy.data.collections.new("Reference lighting and camera")
    scene.collection.children.link(studio)
    for axis in (-1, 1):
        lamp = bpy.data.lights.new(f"Atlas light {axis}", "AREA")
        lamp.energy = 220
        lamp.shape = "DISK"
        lamp.size = 4
        light = bpy.data.objects.new(lamp.name, lamp)
        studio.objects.link(light)
        light.location = center + Vector((2.3 * axis, 2.8 * axis, 2.1))
        aim(light, center)
    camera = bpy.data.objects.new("Atlas reference camera", bpy.data.cameras.new("Atlas reference camera"))
    studio.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 1.10 * (upper.z - lower.z)
    for name, orient in (("anterior", 1), ("posterior", -1)):
        camera.location = center + Vector((0, 4 * direction * orient, 0))
        aim(camera, center)
        scene.render.filepath = str(OUT / (name + ".png"))
        bpy.ops.render.render(write_still=True)
    camera.location = center + Vector((0, 4 * direction, 0))
    aim(camera, center)
    return {"camera_up": "Blender Z", "anterior_world_y_sign": direction,
            "backend": "optix" if DEVICE == "gpu" else "cpu", "devices": chosen}


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath="/atlas.glb")
    bpy.context.view_layer.update()
    scene = bpy.context.scene
    shown, rows = inspect_meshes()
    report = {
        "status": "SOURCE_REFERENCE_ONLY",
        "source_url": SOURCE_URL, "sha256": SOURCE_SHA256, "license": "CC-BY-4.0",
        "attribution": "BodyParts3D © Database Center for Life Science (DBCLS); adapted and rigged by MyoSuite",
        "source_pose": "MyoSuite myoMimicFullbody-v0 bind pose",
        "display": "Procedural fibres in fixed mesh coordinates; no geometry or pose changes",
        "source_objects": len(rows), "visible_unreviewed_objects": len(shown),
        "excluded_cardiac_objects": len(rows) - len(shown),
        "confirmed_on_ms_human_700": 0, "skeletal_muscle_coverage": None,
        "objects": rows,
    }
    report["render"] = render_views(scene, shown)
    notes = bpy.data.texts.new("Reference atlas · provenance")
    notes.write(json.dumps({k: v for k, v in report.items() if k != "objects"}, indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "reference-atlas.blend"), compress=True)
    (OUT / "inventory.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print({k: v for k, v in report.items() if k != "objects"}, flush=True)


if __name__ == "__main__":
    main()
