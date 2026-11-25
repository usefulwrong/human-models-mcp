"""Import, save, reopen and render the same MotionScene using Blender's glTF importer."""

import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb import array, unpack


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def camera(scene, collection, name, view, basis):
    data = bpy.data.cameras.new(name)
    data.lens_unit = "FOV"
    data.sensor_fit = "VERTICAL"
    data.angle = np.deg2rad(view["fov"])
    data.clip_start = .015
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = basis.T @ np.array(view["position"])
    target = Vector(basis.T @ np.array(view["target"]))
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def build(folder, motion, basis, *, save=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 25
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    bpy.ops.import_scene.gltf(filepath=str(folder / "motion.glb"), import_pack_images=False, merge_vertices=False)
    collections = {name: bpy.data.collections.new(name) for name in motion["layers"]}
    for collection in collections.values():
        scene.collection.children.link(collection)
    for obj in list(scene.objects):
        # Blender's glTF importer creates a bone-shape helper in a hidden collection.
        if any(c.name == "glTF_not_exported" for c in obj.users_collection):
            obj.hide_render = True
            continue
        layer = obj.get("layer") or (obj.parent.get("layer") if obj.parent else None)
        target = collections[layer or "MUSCLES"]
        for parent in list(obj.users_collection):
            parent.objects.unlink(obj)
        target.objects.link(obj)
    for name, layer in motion["layers"].items():
        collections[name]["mode"] = layer["mode"]
        collections[name]["available"] = layer["available"]
        collections[name]["description"] = layer["description"]
        shown = name in motion["default_layers"]
        collections[name].hide_render = not shown
        bpy.context.view_layer.layer_collection.children[name].hide_viewport = not shown
    scene.world = bpy.data.worlds.new("Studio world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.20, .25, .33, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = .43
    studio = bpy.data.collections.new("STUDIO")
    scene.collection.children.link(studio)
    for name, pos, power, size in [
        ("Soft key", (.67, -1.45, 2.45), 150, 2.1),
        ("Warm rim", (.89, .95, 1.43), 110, 1.37),
        ("Head fill", (2.4, -.2, 1.15), 40, 1.2),
    ]:
        lamp = bpy.data.lights.new(name, "AREA")
        lamp.energy, lamp.size = power, size
        obj = bpy.data.objects.new(name, lamp)
        studio.objects.link(obj)
        obj.location = pos
        obj.rotation_euler = (Vector((.8, 0, .25)) - obj.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera(scene, studio, "Research side", motion["cameras"]["side"], basis)
    camera(scene, studio, "Cinematic oblique", motion["cameras"]["oblique"], basis)
    camera(scene, studio, "Research torso", motion["cameras"]["torso"], basis)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 800, 560
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.frame_start = 0
    scene.frame_end = len(motion["frames"]) - 1
    for frame in motion["frames"]:
        if frame["phase"] != "motion":
            scene.timeline_markers.new(frame["phase"], frame=frame["state_index"])
    scene.frame_set(0)
    notes = bpy.data.texts.new("MotionScene evidence and attribution")
    notes.write("Assisted MuJoCo push-up. The baked animation is editable. Anatomy registration is illustrative.\n"
                "MyoSuite / BodyParts3D © DBCLS, CC BY 4.0. Z-Anatomy rectus © Gauthier Kervyn, based on "
                "BodyParts3D © DBCLS, CC BY-SA 4.0. MS-Human-700 Apache-2.0.\n")
    notes.write(json.dumps({k: motion[k] for k in ("run_id", "control", "frames", "acceptance", "assets")},
                           indent=2))
    scene["motion_sha256"] = digest(folder / "motion.json")
    scene["trajectory_sha256"] = motion["trajectory_sha256"]
    bpy.context.preferences.filepaths.save_version = 0
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / "render/scene.blend"), compress=True)


def verify(folder, motion, basis):
    scene = bpy.context.scene
    assert scene["motion_sha256"] == digest(folder / "motion.json")
    assert scene["trajectory_sha256"] == motion["trajectory_sha256"]
    samples = json.loads((folder / "samples.json").read_text())
    coverage = json.loads((folder / "coverage.json").read_text())
    assert all(bpy.data.collections.get(name) is not None for name in motion["layers"])
    print("action ranges", sorted({tuple(a.frame_range) for a in bpy.data.actions}))
    native = {row["name"]: row for row in coverage["native_bones"]}
    sample_objs = [scene.objects[s["name"]] for s in samples["points"]]
    doc, blob = unpack((folder / "motion.glb").read_bytes())
    mapped_samples = []
    for row, obj in zip(samples["points"], sample_objs, strict=True):
        mesh_id = doc["nodes"][row["node"]]["mesh"]
        primitive, = doc["meshes"][mesh_id]["primitives"]
        used = np.unique(array(doc, blob, primitive["indices"]))
        if len(used) != len(obj.data.vertices):
            raise ValueError(f"Blender importer topology differs from source for {obj.name}")
        verified = []
        for i, vertex in enumerate(row["vertices"]):
            at = int(np.searchsorted(used, vertex))
            if at < len(used) and used[at] == vertex:
                verified.append((at, i))
        if not verified:
            raise ValueError(f"no used sample vertices remain for {obj.name}")
        remap, keep = zip(*verified, strict=True)
        mapped_samples.append((remap, np.asarray(row["world_glb_m"])[:, keep, :] @ basis))
    poses = {int(g): np.asarray(p) for g, p in samples["geom_pose_world_m"].items()}
    errors, skin_errors, frame_rows = [], [], []
    for i, frame in enumerate(motion["frames"]):
        scene.frame_set(i)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        error = 0.
        for obj, (remap, exp) in zip(sample_objs, mapped_samples, strict=True):
            evaluated = obj.evaluated_get(depsgraph)
            transform = np.asarray(evaluated.matrix_world)
            xyz = np.array([evaluated.data.vertices[j].co for j in remap])
            xyz = xyz @ transform[:3, :3].T + transform[:3, 3]
            values = np.linalg.norm(xyz - exp[i], axis=1)
            errors.extend(values)
            if obj.name in native:
                g = native[obj.name]["geom_id"]
                error = max(error, float(np.max(np.abs(transform - poses[g][i]))))
            else:
                skin_errors.extend(values)
        frame_rows.append({"source_index": i, "state_sha256": frame["state_sha256"],
                           "native_transform_sha256": frame["native_transform_sha256"],
                           "max_native_matrix_component_error": error})
    result = {"frames": frame_rows, "points_per_frame": sum(len(remap) for remap, _ in mapped_samples),
              "point_max_m": float(max(errors)), "point_rms_m": float(np.sqrt(np.mean(np.square(errors)))),
              "skin_max_m": float(max(skin_errors)), "skin_rms_m": float(np.sqrt(np.mean(np.square(skin_errors)))),
              "maximum_native_matrix_component_error": max(row["max_native_matrix_component_error"] for row in frame_rows),
              "action_count": len(bpy.data.actions), "armatures": [o.name for o in scene.objects if o.type == "ARMATURE"],
              "collections": {c: len(bpy.data.collections[c].objects) for c in motion["layers"]}}
    result["blender_vertex_samples"] = {row["name"]: list(remap) for row, (remap, _) in
                                         zip(samples["points"], mapped_samples, strict=True)}
    (folder / "render/reopen.json").write_text(json.dumps(result, indent=2) + "\n")
    print({k: v for k, v in result.items() if k not in {"frames", "blender_vertex_samples"}}, flush=True)
    if result["point_max_m"] > .0001 or result["maximum_native_matrix_component_error"] > .0001:
        raise ValueError("Blender keyframe/geometry parity exceeded 0.1 mm/matrix component bound")


def render(folder, motion):
    scene = bpy.context.scene
    preferences = bpy.context.preferences.addons["cycles"].preferences
    preferences.compute_device_type = "CUDA"
    preferences.refresh_devices()
    devices = [device for device in preferences.devices if device.type == "CUDA"]
    if not devices:
        raise RuntimeError("CUDA render requested without CUDA device")
    for device in preferences.devices:
        device.use = device.type == "CUDA"
    print("CYCLES CUDA", [(d.name, d.type, d.use) for d in preferences.devices], flush=True)
    scene.cycles.device = "GPU"
    indices = [f["state_index"] for f in motion["frames"] if f["phase"] != "motion"]
    sequence = sorted(set(range(0, scene.frame_end + 1, 5)) | set(indices))
    for i, frame in enumerate(sequence):
        scene.frame_set(frame)
        scene.render.filepath = str(folder / f"render/video-{i:03d}.png")
        bpy.ops.render.render(write_still=True)
    scene.camera = bpy.data.objects["Cinematic oblique"]
    scene.frame_set(indices[1])
    scene.render.filepath = str(folder / "render/oblique-bottom.png")
    bpy.ops.render.render(write_still=True)
    scene.camera = bpy.data.objects["Research torso"]
    scene.render.filepath = str(folder / "render/torso-bottom.png")
    bpy.ops.render.render(write_still=True)


def main():
    folder, operation = sys.argv[sys.argv.index("--") + 1:]
    folder = Path(folder)
    motion = json.loads((folder / "motion.json").read_text())
    basis = np.asarray(motion["coordinates"]["world_to_glb"])[:3, :3]
    if digest(folder / "motion.glb") != motion["artifacts"]["motion.glb"]["sha256"]:
        raise ValueError("motion GLB digest differs")
    if operation == "build":
        build(folder, motion, basis)
    elif operation == "verify":
        verify(folder, motion, basis)
    elif operation == "render":
        render(folder, motion)
    else:
        raise ValueError("unknown operation")


if __name__ == "__main__":
    main()
