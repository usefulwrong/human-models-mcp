"""Reopen the whole-body scene for intersections, then inspect the bounded GLB probes."""

import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np
from mathutils import Vector

FOLDER, SCRIPTS, NATIVE = (Path(x) for x in sys.argv[sys.argv.index("--") + 1:])
sys.path[:0] = [str(SCRIPTS), str(Path(__file__).resolve().parent)]
from atlas_collision_blender import bone_surfaces, check_detector, intersections, surface, tree  # noqa: E402
from atlas_arm_surface_blender import self_pairs  # noqa: E402
from glb import array, unpack  # noqa: E402


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    motion = json.loads((FOLDER / "motion.json").read_bytes())
    geometry = json.loads((FOLDER / "geometry.json").read_bytes())
    sites = json.loads(NATIVE.read_bytes()).get("key_model_sites", {})
    basis = np.asarray(motion["coordinates"]["world_to_glb"])[:3, :3]
    scene = bpy.context.scene
    out = FOLDER / "experiments"
    out.mkdir(exist_ok=True)
    check_detector()
    qa = {}
    check_names = ("FJ1447", "FJ1447M", "FJ1446", "FJ1446M", "FJ1477", "FJ1477M", "FJ1414M")
    for k in geometry["probe_indices"]:
        scene.frame_set(k)
        graph = bpy.context.evaluated_depsgraph_get()
        endpoints = sites.get(str(k), {})
        bones = bone_surfaces(bpy.data.collections["SKELETON"].objects, graph)
        rows = {}
        for obj in bpy.data.collections["MUSCLES"].objects:
            if obj.type != "MESH":
                continue
            points, faces = surface(obj, graph)
            hits = intersections(points, faces, bones)
            row = {"bone_triangle_pair_counts": hits}
            if any(f"[{fj}]" in obj.name for fj in check_names):
                bvh = tree(points, faces)
                _, weld = np.unique(points, axis=0, return_inverse=True)
                row["self_nonadjacent_pairs"] = len(self_pairs(bvh, faces, weld))
                if "[FJ1447]" in obj.name or "[FJ1447M]" in obj.name:
                    side = "r" if "[FJ1447]" in obj.name else "l"
                    row["native_path_site_to_surface_m"] = {
                        s: bvh.find_nearest(Vector(p))[3] for s, p in endpoints.items() if s.startswith("PECM1_" + side)
                    }
            if hits or len(row) > 1:
                rows[obj.name] = row
        qa[k] = rows
    dump(out / "crossings.json", {"geometry": "reopened Blender meshes", "frames": qa,
          "limitations": "Triangle overlaps include intended attachments and source noise. No tissue collision model."})
    stage = bpy.data.collections.new("INTERCHANGE PROBES")
    scene.collection.children.link(stage)
    scene.render.resolution_percentage = 70
    scene.cycles.samples = 6
    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.refresh_devices()
    assert any(d.type == "CUDA" for d in prefs.devices)
    for d in prefs.devices:
        d.use = d.type == "CUDA"

    def new_objects(clip):
        before = set(scene.objects)
        started = perf_counter()
        bpy.ops.import_scene.gltf(filepath=str(FOLDER / (clip + "-probe.glb")), merge_vertices=False)
        objects = list(set(scene.objects) - before)
        for obj in objects:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            stage.objects.link(obj)
        return objects, perf_counter() - started

    def shot(name):
        scene.render.filepath = str(out / (name + ".png"))
        bpy.ops.render.render(write_still=True)

    bp, elapsed = new_objects("bp3d")
    for name in ("MUSCLES", "SKELETON"):
        bpy.data.collections[name].hide_render = True
    for i in (0, 55, 110):
        scene.frame_set(i)
        for variant in ("before", "fit"):
            for obj in bp:
                obj.hide_render = bool(obj.name.endswith(("_before", "_fit"))) and not obj.name.endswith("_" + variant)
            shot(f"bp3d-{variant}-{i:03d}")
    stage.hide_render = True
    for name in ("MUSCLES", "SKELETON"):
        bpy.data.collections[name].hide_render = False
    scene.frame_set(55)
    scene.camera = bpy.data.objects["Research torso"]
    overlays = bpy.data.collections["OVERLAYS"]
    overlays.hide_render = False
    shot("native-pads-055")
    overlays.hide_render = True
    measurements = {"bp3d_blender_import_s": elapsed}
    for kind in ("baked", "sharpened"):
        candidates, elapsed = new_objects(kind)
        obj, = [o for o in candidates if o.type == "MESH"]
        source = FOLDER / (kind + "-probe")
        values = json.loads(source.with_suffix(".json").read_bytes())
        doc, blob = unpack(source.with_suffix(".glb").read_bytes())
        used = np.unique(array(doc, blob, doc["meshes"][0]["primitives"][0]["indices"]))
        errors = []
        for t, xyz in zip(values["times_s"], values["world_glb_m"], strict=True):
            scene.frame_set(round(t * 25))
            calc = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            at = np.searchsorted(used, values["vertex_indices"])
            assert np.array_equal(used[at], values["vertex_indices"])
            actual = np.array([calc.matrix_world @ calc.data.vertices[i].co for i in at])
            errors.extend(np.linalg.norm(actual - np.array(xyz) @ basis, axis=1))
        measurements[kind] = {"bytes": source.with_suffix(".glb").stat().st_size, "import_s": elapsed,
                              "point_max_m": float(max(errors)), "point_rms_m": float(np.sqrt(np.mean(np.square(errors)))),
                              "shape_keys": len(obj.data.shape_keys.key_blocks), "times_s": values["times_s"],
                              "vertex_indices": values["vertex_indices"]}
        assert max(errors) < .0001
        scene.frame_set(55)
        stage.hide_render = False
        for other in stage.objects:
            other.hide_render = other != obj
        original = bpy.data.objects["Clavicular part of right pectoralis major [FJ1447]"]
        original.hide_render = True
        shot(kind + "-right-pectoralis-055")
        original.hide_render = False
        stage.hide_render = True
    dump(out / "interchange.json", measurements)
    print(measurements)


if __name__ == "__main__":
    main()
