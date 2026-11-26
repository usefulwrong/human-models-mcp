"""Replay official MCP selection receipts in an editable copy of the exact MotionScene."""

import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
from mathutils import Vector
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "scripts/anatomy_lab/moving"), str(ROOT / "scripts")]
from blender import build as build_scene, digest  # noqa: E402
from glb import BASIS, Clip, array, unpack, face_vectors  # noqa: E402
from atlas_collision_blender import bone_surfaces, check_detector, intersections, surface, tree  # noqa: E402
from atlas_arm_surface_blender import relax, self_pairs, topology  # noqa: E402

FRAMES = (0, 27, 55, 83, 110)


def dump(path, value):
    path.write_text(json.dumps(value, allow_nan=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def objects():
    return {int(o["source_node"]): o for o in bpy.context.scene.objects if "source_node" in o and o.type == "MESH"}


def activate(group):
    for obj in objects().values():
        if "muscle_group" in obj:
            name = obj["muscle_overlay"] if obj["muscle_group"] == group else obj["anatomical_material"]
            obj.data.materials[0] = bpy.data.materials[name]


def find_color(mat):
    return mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"]


def overlay(folder, output, evidence, crosswalk=None, controls=None):
    motion = json.loads((folder / "motion.json").read_bytes())
    if digest(folder / "motion.glb") != motion["artifacts"]["motion.glb"]["sha256"]:
        raise ValueError("motion GLB digest differs")
    build_scene(folder, motion, BASIS, save=False)
    scene = bpy.context.scene
    source = objects()
    envelope = json.loads(evidence.read_bytes())
    received = envelope.get("groups", envelope)
    views = json.loads(controls.read_bytes()) if controls else envelope.get("views", {})
    chosen = envelope.get("open_selection")
    if any(row["selection"]["motion_sha256"] != scene["motion_sha256"] or
           row["selection"]["run_id"] != motion["run_id"] or
           row["selection"]["source_result_sha256"] != motion["source_manifest_sha256"]
           for row in received.values()):
        raise ValueError("Blender input receipts belong to a different run")
    mapping = {row["selection"]["mapping_revision_sha256"] for row in received.values()}
    mapping.update(view["mapping_revision_sha256"] for view in views.values())
    if len(mapping) != 1:
        raise ValueError("more than one crosswalk revision")
    scene["muscle_mapping_sha256"] = mapping.pop()
    scene["run_id"] = motion["run_id"]
    page = bpy.data.texts.new("Saved native selections and exact signal values")
    doc, blob = unpack((folder / "motion.glb").read_bytes())
    samples = json.loads((folder / "samples.json").read_bytes())
    provenance = {}
    if crosswalk:
        if digest(crosswalk) != scene["muscle_mapping_sha256"]:
            raise ValueError("Blender crosswalk differs from MCP receipts")
        identities = json.loads(crosswalk.read_bytes())
        scene["crosswalk_revision"] = identities.get("coverage_revision", 1)
        for key, asset in identities["motion_display_assets"].items():
            kind = identities["reviewed_display_assets"].get(key)
            obj = scene.objects[doc["nodes"][int(key)]["name"]]
            obj["motion_node"] = int(key)
            obj["display_asset_id"] = asset["mesh_id"]
            obj["display_source"] = asset["dataset"]
            obj["display_sha256"] = asset["geometry_sha256"]
            obj["display_fma_id"] = asset.get("fma_id") or ""
            obj["display_mapping_status"] = ("REVIEWED_ANATOMICAL" if kind and kind["part_actuator_id"] is not None
                                             else "REVIEWED_GROUP_ONLY" if kind else "GEOMETRY_ONLY")
            obj["display_registration"] = asset["registration"]
            obj["attachment_footprint"] = asset.get("attachment_validation", "NOT_VERIFIED")
            obj["deformation_validation"] = asset.get("deformation_validation", "NOT_VERIFIED")
        scene["muscle_display_count"] = len(identities["motion_display_assets"])
    if views:
        for result in views.values():
            if (result["motion_sha256"] != scene["motion_sha256"] or result["run_id"] != scene["run_id"]
                    or result["mapping_revision_sha256"] != scene["muscle_mapping_sha256"]
                    or result["frame"] != motion["frames"][result["frame"]["state_index"]]):
                raise ValueError("Blender selected view differs from run or mapping")
            if registration := result.get("registration"):
                for key in ("run_id", "motion_sha256", "mapping_revision_sha256", "crosswalk_revision", "frame",
                            "mapping_status"):
                    if registration[key] != result[key]:
                        raise ValueError(f"Blender registration receipt disagrees on {key}")
            if result["display_nodes"] and not all(
                    scene.objects[doc["nodes"][i]["name"]].get("motion_node") == i for i in result["display_nodes"]):
                raise ValueError("Blender selected view node is unavailable")
        bpy.data.texts.new("Native and surface selection receipts").write(json.dumps(views, ensure_ascii=True))
    for group, record in received.items():
        selection = record["selection"]
        asset = selection["asset"]
        nodes = selection["overlay"]["display_nodes"]
        activation = record["entries"]["activation"]
        if (activation["state_indices"] != list(range(len(motion["frames"])))
                or activation["time_s"] != [f["frame_time"] for f in motion["frames"]]):
            raise ValueError("MCP and Blender clocks differ")
        picked = source[asset["source_node"]]
        sample = next(s for s in samples["points"] if s["node"] == asset["display_copy"])
        mesh = doc["meshes"][doc["nodes"][asset["display_copy"]]["mesh"]]["primitives"][0]
        used = np.unique(array(doc, blob, mesh["indices"]))
        if len(used) != len(picked.data.vertices):
            raise ValueError("glTF importer topology differs")
        samples_pairs = [(int(np.searchsorted(used, idx)), k) for k, idx in enumerate(sample["vertices"]) if idx in used]
        material = picked.data.materials[0].copy()
        material.name = f"Model activation | {group}"
        material.use_fake_user = True
        color = find_color(material)
        zero = np.array(selection["overlay"]["linear_rgb_at_0"])
        one = np.array(selection["overlay"]["linear_rgb_at_1"])
        for index, value in enumerate(activation["aggregate"]):
            rgba = [*(zero + (one - zero) * np.clip(value, 0, 1)), 1]
            material.diffuse_color = rgba
            material.keyframe_insert(data_path="diffuse_color", frame=index)
            color.default_value = rgba
            color.keyframe_insert(data_path="default_value", frame=index)
        group_collection = bpy.data.collections.new(group.replace("_", " "))
        scene.collection.children["MUSCLES"].children.link(group_collection)
        for node in nodes:
            node_data = doc["nodes"][node]["extras"]
            obj = source[node_data["source_node"]]
            obj["muscle_group"] = group
            obj["motion_node"] = node
            obj["anatomical_material"] = obj.data.materials[0].name
            obj.data.materials[0].use_fake_user = True
            obj["muscle_overlay"] = material.name
            scene.collection.children["MUSCLES"].objects.unlink(obj)
            group_collection.objects.link(obj)
        anchor = selection["frame"]["state_index"]
        provenance[group] = {"asset": asset, "selection": selection["selection"], "overlay": selection["overlay"],
            "frame": selection["frame"], "data": selection["sample"], "material": material.name,
            "world_points_glb_m": [sample["world_glb_m"][anchor][j] for _, j in samples_pairs],
            "vertex_ids": [i for i, _ in samples_pairs], "activation": activation,
            "acceptance": selection["acceptance"],
            **({"scientific_quantity": selection["scientific_quantity"]} if "scientific_quantity" in selection else {})}
    page.write(json.dumps(provenance, ensure_ascii=True))
    if chosen:
        receipt = views[chosen]
        selection = receipt["selection"]
        group = receipt["group"]["group_id"] if selection["overlay"] else None
        if selection["overlay"] and group not in received:
            raise ValueError("selected activation colors require saved group samples")
        activate(group)
        scene["selected_receipt"] = chosen
        for obj in list(scene.collection.children["MUSCLES"].all_objects):
            if obj.type != "MESH":
                continue
            selected = obj.get("motion_node") in receipt["display_nodes"]
            if selection["isolate"] and not selected:
                obj.hide_render = True
                obj.hide_viewport = True
            if obj.get("motion_node") in receipt.get("opacity_nodes", receipt["display_nodes"]) and selection["opacity"] < 1:
                mat = obj.data.materials[0].copy()
                obj["selected_material_original"] = obj.data.materials[0].name
                obj.data.materials[0] = mat
                mat.node_tree.nodes.get("Principled BSDF").inputs["Alpha"].default_value = selection["opacity"]
        scene.frame_set(receipt["frame"]["state_index"])
    else:
        activate("pectoralis_major:right")
        scene.frame_set(55)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "muscle-intelligence.blend"), compress=True)
    print("Editable Blender archive written", flush=True)


def reopen(output):
    scene = bpy.context.scene
    values = json.loads(bpy.data.texts["Saved native selections and exact signal values"].as_string())
    receipts = {}
    expected_start = 55
    opening_view = None
    if chosen := scene.get("selected_receipt"):
        extra = json.loads(bpy.data.texts["Native and surface selection receipts"].as_string())
        selected = extra[chosen]
        expected_start = selected["frame"]["state_index"]
        nodes = [o for o in scene.objects if o.type == "MESH" and "motion_node" in o]
        visible = sorted(o["motion_node"] for o in nodes if not o.hide_render and not o.hide_viewport)
        if selected["selection"]["isolate"]:
            assert visible == sorted(selected["display_nodes"])
        opacity = {}
        for obj in nodes:
            if obj["motion_node"] in selected.get("opacity_nodes", selected["display_nodes"]):
                alpha = obj.data.materials[0].node_tree.nodes.get("Principled BSDF").inputs["Alpha"].default_value
                assert abs(alpha - selected["selection"]["opacity"]) < 1e-6
                opacity[obj["motion_node"]] = alpha
        opening_view = {"visible_display_nodes": visible, "selected_alpha": opacity, "frame": expected_start}
    assert scene.frame_current == expected_start
    for group, record in values.items():
        activate(group)
        obj = objects()[record["asset"]["source_node"]]
        hidden = obj.hide_viewport
        obj.hide_viewport = False
        scene.frame_set(record["frame"]["state_index"])
        assert scene.frame_current == record["frame"]["state_index"]
        assert obj["motion_node"] == record["selection"]["display_node"]
        mat = obj.data.materials[0]
        rgb = np.array(find_color(mat).default_value[:3])
        error_color = float(np.max(np.abs(rgb - record["overlay"]["linear_rgb"])))
        assert error_color < 1e-6
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        world = np.asarray([list(evaluated.matrix_world @ evaluated.data.vertices[i].co)
                            for i in record["vertex_ids"]]) @ BASIS.T
        delta = float(np.max(np.linalg.norm(world - record["world_points_glb_m"], axis=1)))
        assert delta < .0001
        assert scene["run_id"] and scene["muscle_mapping_sha256"]
        evidence = record.get("scientific_quantity")
        if evidence:
            frame = record["frame"]
            assert evidence["run_id"] == scene["run_id"]
            assert evidence["motion_sha256"] == scene["motion_sha256"]
            assert evidence["mapping_revision_sha256"] == scene["muscle_mapping_sha256"]
            assert evidence["window"]["state_index"] == frame["state_index"]
            assert evidence["window"]["state_sha256"] == frame["state_sha256"]
            assert evidence["window"]["time_s"] == frame["frame_time"]
            assert evidence["quantities"][record["selection"]["metric"]]["availability"] == "AVAILABLE"
        receipts[group] = {"asset": record["asset"], "frame": record["frame"], "max_point_error_m": delta,
                           "color_error": error_color, "rgb_linear": rgb.tolist(), "raw_sample": record["data"],
                           **({"scientific_quantity": evidence} if evidence else {}),
                           "world_glb_m": world.tolist()}
        obj.hide_viewport = hidden
    controls = {}
    if stored := bpy.data.texts.get("Native and surface selection receipts"):
        selected = json.loads(stored.as_string())
        by_node = {o["motion_node"]: o for o in scene.objects if o.type == "MESH" and "motion_node" in o}
        for label, result in selected.items():
            scene.frame_set(result["frame"]["state_index"])
            controls[label] = {k: result.get(k) for k in ("frame", "asset", "sample", "mapping_status", "scientific_quantity")}
            controls[label]["display_ids"] = [by_node[i]["display_asset_id"] for i in result["display_nodes"]]
            if "registration" in result:
                controls[label]["registration"] = result["registration"]
                for metric, curve in result["curves"].items():
                    assert curve["metric"] == metric and curve["motion_sha256"] == scene["motion_sha256"]
                    assert curve["mapping_revision_sha256"] == scene["muscle_mapping_sha256"]
                    index = result["frame"]["state_index"]
                    assert curve["time_s"][index] == result["frame"]["frame_time"]
                    if metric == result["selection"]["metric"]:
                        assert [r["values"][index] for r in curve["series"]] == [
                            r["values"][0] for r in result["sample"]["series"]]
            if not result["group"] and result["asset"]:
                assert result.get("sample") is None and "overlay" not in result
    scene.frame_set(expected_start)
    dump(output / "blender-parity.json", {"run_id": scene["run_id"], "motion_sha256": scene["motion_sha256"],
         "mapping_revision_sha256": scene["muscle_mapping_sha256"],
         "crosswalk_revision": scene.get("crosswalk_revision"),
         "active_scene_frame": scene.frame_current, "packed_without_external_gltf": not bpy.data.libraries,
         "opening_selection": opening_view,
         "moving_muscle_objects": scene.get("muscle_display_count"), "selection_controls": controls,
         "groups": receipts})
    print(f"PASS Blender reopen: {len(receipts)} linked selections, {len(controls)} additional receipts.", flush=True)


def setup_render(scene):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "CUDA"
    devices = [d.name for d in prefs.devices if d.use]
    if not devices:
        raise RuntimeError("CUDA device unavailable")
    print("Cycles CUDA:", devices, flush=True)
    scene.cycles.device = "GPU"
    scene.cycles.samples = 8
    scene.render.resolution_x, scene.render.resolution_y = 640, 420
    scene.render.resolution_percentage = 100


def still(scene, path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render(output):
    scene = bpy.context.scene
    setup_render(scene)
    activate("pectoralis_major:right")
    scene.camera = bpy.data.objects["Research side"]
    sequence = sorted({*range(0, 111, 10), *FRAMES})
    for i, index in enumerate(sequence):
        scene.frame_set(index)
        still(scene, output / f"video-{i:03d}.png")
    activate("triceps_brachii:right")
    scene.camera = bpy.data.objects["Research torso"]
    scene.frame_set(55)
    still(scene, output / "blender-triceps-055.png")
    dump(output / "video-frames.json", {"state_indices": sequence, "frame_times_s": [i / 25 for i in sequence],
         "input_cadence": "nonuniform exact saved samples; MP4 holds each sample for its original time interval",
         "run_id": scene["run_id"], "mapping_revision_sha256": scene["muscle_mapping_sha256"]})


def regions(output):
    scene = bpy.context.scene
    setup_render(scene)
    scene.render.resolution_x, scene.render.resolution_y = 480, 320
    muscles = [o for o in scene.collection.children["MUSCLES"].all_objects if o.type == "MESH"]
    by_id = {o.get("motion_node"): o for o in muscles}
    scene.camera = camera = bpy.data.objects["Research torso"]
    camera.data.type = "ORTHO"
    for label, node, group, scale in [
        ("chest", 239, "pectoralis_major:right", .49),
        ("torso", 402, None, .64),
        ("leg", 457, "soleus:right", .57),
    ]:
        target = by_id[node]
        activate(group)
        selected = [obj for obj in muscles if obj == target or group and obj.get("muscle_group") == group]
        for obj in muscles:
            obj.hide_render = obj not in selected
        phase_camera(scene, camera, selected, FRAMES, scale)
        for frame in FRAMES:
            scene.frame_set(frame)
            still(scene, output / f"{label}-{frame:03}.png")
    for obj in muscles:
        obj.hide_render = False


def phase_camera(scene, camera, meshes, frames, min_width):
    bounds = []
    for frame in frames:
        scene.frame_set(frame)
        graph = bpy.context.evaluated_depsgraph_get()
        for mesh in meshes:
            vertices, _ = surface(mesh, graph)
            bounds.extend((vertices.min(0), vertices.max(0)))
    low, high = np.min(bounds, axis=0), np.max(bounds, axis=0)
    center = Vector((low + high) / 2)
    camera.location = center + Vector((.3, -1.3, .24))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.ortho_scale = max(min_width, float(np.linalg.norm(high - low)) * 1.65)


def clearance(points, faces, bones, references):
    atlas = tree(points, faces)
    count, outside = 0, 0
    centers = points[faces].mean(axis=1)
    for _, low, high, neighbor in bones:
        if (points.max(0) < low).any() or (high < points.min(0)).any():
            continue
        pairs = atlas.overlap(neighbor)
        if pairs:
            ids = np.asarray(pairs)[:, 0]
            count += len(ids)
            if references is not None:
                outside += int(np.count_nonzero(np.linalg.norm(
                    centers[ids, None] - references, axis=2).min(axis=1) > .015))
    return count, outside if references is not None else None


def quality(points, before, faces, weld, endpoints, bones, closed):
    area = face_vectors(points, faces)
    comparison = face_vectors(before, faces)
    mesh = tree(points, faces)
    near = [float(mesh.find_nearest(Vector(p))[3]) for p in endpoints] if endpoints is not None else None
    n, outside = clearance(points, faces, bones, endpoints)
    volume = float(abs(np.einsum("ij,ij->i", points[faces[:, 0]], area).sum()) / 6) if closed else None
    return {"bone_intersection_pairs": n, "outside_15mm_endpoint_zone": outside,
            "self_intersection_pairs": len(self_pairs(mesh, faces, weld)),
            "floor_crossing_triangles": int(np.count_nonzero((points[faces, 2].min(1) < 0) &
                                                              (points[faces, 2].max(1) >= 0))),
            "min_floor_height_m": float(points[:, 2].min()), "endpoint_gap_m": near,
            "against_baseline_normal_faces": int(np.count_nonzero(np.sum(area * comparison, axis=1) < 0)),
            "small_area_proxy_faces": int(np.count_nonzero(np.linalg.norm(area, axis=1) < 1e-10)),
            "surface_area_m2": float(np.linalg.norm(area, axis=1).sum() / 2),
            "closed_oriented_volume_m3": volume}


def is_closed(faces, weld):
    tris = weld[faces]
    edges = tris[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    _, ids, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    directions = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    return bool((edges[:, 0] != edges[:, 1]).all() and (counts == 2).all() and
                not np.bincount(ids, weights=directions).any())


def dual_quaternion(output, endpoints_path):
    scene = bpy.context.scene
    native = json.loads(endpoints_path.read_bytes())
    by_id = {o.get("motion_node"): o for o in scene.collection.children["MUSCLES"].all_objects if o.type == "MESH"}
    targets = [(239, "PECM1_r", "chest"), (237, "PECM1_l", "chest"), (460, "SUBSC_r", "deep_shoulder"),
               (402, None, "torso"), (457, "soleus_r", "leg"), (348, "soleus_l", "leg")]
    cases = {}
    scene.frame_set(0)
    graph = bpy.context.evaluated_depsgraph_get()
    for node, path, region in targets:
        obj = by_id[node]
        modifier, = (m for m in obj.modifiers if m.type == "ARMATURE")
        _, faces = surface(obj, graph)
        weld = topology(obj, faces)[1]
        rest = np.asarray([list(obj.matrix_world @ v.co) for v in obj.data.vertices])
        edges = np.unique(np.sort(faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1), axis=0)
        length = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
        cases[node] = (obj, modifier, faces, weld, edges[length > 1e-6], length[length > 1e-6],
                       is_closed(faces, weld), path, region)
    report = {node: {"asset": obj["display_asset_id"], "fma": obj["display_fma_id"], "name": obj.name,
                     "closed_welded_and_oriented": closed, "route": path, "region": region,
                     "vertex_count": len(obj.data.vertices), "frames": {},
                     "largest_interstate_step_m": {"LBS": 0, "DQ": 0}}
              for node, (obj, _, _, _, _, _, closed, path, region) in cases.items()}
    previous = {}
    started = perf_counter()
    for frame in range(scene.frame_end + 1):
        scene.frame_set(frame)
        graph = bpy.context.evaluated_depsgraph_get()
        bones = bone_surfaces(scene.collection.children["SKELETON"].objects, graph) if frame in FRAMES else None
        positions = {}
        for method, use_dq in (("LBS", False), ("DQ", True)):
            for _, modifier, *_ in cases.values():
                modifier.use_deform_preserve_volume = use_dq
            graph = bpy.context.evaluated_depsgraph_get()
            for node, (obj, _, faces, weld, edges, length, closed, path, _) in cases.items():
                points, _ = surface(obj, graph)
                if method == "LBS":
                    positions[node] = points
                key = (node, method)
                if key in previous:
                    step = np.linalg.norm(points - previous[key], axis=1).max()
                    peak = report[node]["largest_interstate_step_m"]
                    peak[method] = max(peak[method], float(step))
                previous[key] = points
                if bones is not None:
                    anchors = np.asarray(native["endpoints_m"][path][frame]) if path else None
                    qa = quality(points, positions[node], faces, weld, anchors, bones, closed)
                    ratios = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1) / length
                    qa["edge_length_ratio_against_mesh_rest"] = np.percentile(ratios, [0, 50, 95, 100]).tolist()
                    report[node]["frames"].setdefault(frame, {})[method] = qa
    elapsed = perf_counter() - started
    dump(output / "GEOMETRY_DQ_QA.json", {"run_id": native["run_id"], "frames": FRAMES, "runtime_cpu_s": elapsed,
         "methods": ["authored moving scene LBS", "Blender armature preserve-volume dual quaternion"],
         "endpoint_exclusion_radius_m": .015, "pieces": report})
    setup_render(scene)
    scene.render.resolution_x, scene.render.resolution_y = 480, 320
    scene.camera = camera = bpy.data.objects["Research torso"]
    camera.data.type = "ORTHO"
    muscle_meshes = [o for o in scene.collection.children["MUSCLES"].all_objects if o.type == "MESH"]
    for node in (239, 460, 402, 457):
        obj, modifier, *_ = cases[node]
        activate(None)
        for item in muscle_meshes:
            item.hide_render = item != obj
        modifier.use_deform_preserve_volume = False
        phase_camera(scene, camera, [obj], (0, 55, 110), .52)
        for method, use_dq in (("LBS", False), ("DQ", True)):
            modifier.use_deform_preserve_volume = use_dq
            for frame in (0, 55, 110):
                scene.frame_set(frame)
                still(scene, output / f"dq-{node}-{method}-{frame:03}.png")
    print(f"PASS same-state six-piece LBS/DQ QA in {elapsed:.3f}s", flush=True)


def pilot(output, endpoints_path):
    scene = bpy.context.scene
    sources = json.loads(bpy.data.texts["Saved native selections and exact signal values"].as_string())
    objects_by_group = objects()
    native = json.loads(endpoints_path.read_bytes())
    held = {name: np.asarray(points) for name, points in native["endpoints_m"].items()}
    paths = [g for g in sources if g.startswith("pectoralis_major")]
    scene.frame_set(0)
    graph = bpy.context.evaluated_depsgraph_get()
    lookup, report, meshes = {}, {}, {}
    for group in paths:
        side = group.split(":")[1][0]
        labels = {"Clavicular": "PECM1_", "Sternocostal": "PECM2_"}
        for obj in objects_by_group.values():
            prefix = obj.name.split()[0]
            if obj.get("muscle_group") == group and prefix in labels:
                code = labels[prefix] + side
                _, faces = surface(obj, graph)
                topo = topology(obj, faces)
                closed = is_closed(faces, topo[1])
                lookup[code] = (obj, faces, topo, closed)
                report[code] = {"name": obj.name, "closed_welded_and_oriented": closed, "frames": {},
                                "baseline_max_vertex_step_m": 0, "candidate_max_vertex_step_m": 0,
                                "max_displacement_m": 0}
                meshes[code] = {"authored_lbs": [], "candidate": []}
    assert len(lookup) == 4
    start = perf_counter()
    before_previous, after_previous = {}, {}
    whole_bottom = {}
    check_detector()
    for frame in range(111):
        scene.frame_set(frame)
        graph = bpy.context.evaluated_depsgraph_get()
        bones = bone_surfaces(scene.collection.children["SKELETON"].objects, graph) if frame in FRAMES else None
        if frame == 55:
            floor_count, crossing_count, total_objects = 0, 0, 0
            for obj in scene.collection.children["MUSCLES"].all_objects:
                if obj.type != "MESH":
                    continue
                pose, tris = surface(obj, graph)
                crossing_count += sum(intersections(pose, tris, bones).values())
                floor_count += bool((pose[:, 2] < 0).any())
                total_objects += 1
            whole_bottom = {"method": "BVH across all animated muscle meshes, count min z < 0 for floors",
                            "mesh_count": total_objects, "bone_muscle_triangle_pairs": crossing_count,
                            "floor_penetrating_surfaces": floor_count}
        for code, (obj, faces, topo, closed) in lookup.items():
            before, _ = surface(obj, graph)
            distance = np.linalg.norm(before[topo[0], None] - held[code][frame], axis=2).min(axis=1)
            weight = np.clip((distance - .015) / .020, 0, 1)
            weight = weight * weight * (3 - 2 * weight)
            after = relax(before, topo, weight, 3, .002)
            row = report[code]
            def norm(value):
                return float(np.linalg.norm(value, axis=1).max())
            row["max_displacement_m"] = max(row["max_displacement_m"], norm(after - before))
            if frame:
                for label, points, previous in (("baseline", before, before_previous), ("candidate", after, after_previous)):
                    key = label + "_max_vertex_step_m"
                    row[key] = max(row[key], norm(points - previous[code]))
            before_previous[code], after_previous[code] = before, after
            if bones is not None:
                row["frames"][str(frame)] = {name: quality(points, before, faces, topo[1], held[code][frame], bones, closed)
                    for name, points in (("authored_lbs", before), ("candidate", after))}
                for key, v in (("authored_lbs", before), ("candidate", after)):
                    meshes[code][key].append(v)
    duration = perf_counter() - start
    bpy.context.scene.collection.children["MUSCLES"].hide_render = True
    setup_render(scene)
    scene.camera = bpy.data.objects["Research torso"]
    scene.camera.location = (1.75, -1.13, .21)
    scene.camera.rotation_euler = (Vector((1.24, 0, .38)) - scene.camera.location).to_track_quat("-Z", "Y").to_euler()
    candidates = bpy.data.collections.new("Local pilot film comparison")
    scene.collection.children.link(candidates)
    sizes = {}
    for name in ("authored_lbs", "candidate"):
        clip = Clip(np.asarray(FRAMES) / 25)
        flat = []
        for code, records in meshes.items():
            obj, faces, _, _ = lookup[code]
            snapshots = records[name]
            mat = clip.material("Pectoralis pilot", [.51, .10, .081])
            node, prim = clip.mesh(code, "MUSCLES", snapshots[0] @ BASIS.T, faces, mat)
            prim["targets"] = [{"POSITION": clip.accessor((row - snapshots[0]) @ BASIS.T, "VEC3", target=34962)}
                               for row in snapshots[1:]]
            clip.channel(node, "weights", np.eye(len(FRAMES))[:, 1:].ravel(), "SCALAR")
            mesh = bpy.data.meshes.new(code)
            mesh.from_pydata(snapshots[0].tolist(), [], faces.tolist())
            for poly in mesh.polygons:
                poly.use_smooth = True
            item = bpy.data.objects.new(code, mesh)
            candidates.objects.link(item)
            material = bpy.data.materials[obj["anatomical_material"]]
            item.data.materials.append(material)
            flat.append((item, snapshots))
        path = output / f"pectoral-{name}.glb"
        clip.finish(path)
        sizes[name] = path.stat().st_size
        for frame_pos, frame in enumerate(FRAMES):
            scene.frame_set(frame)
            for item, snapshots in flat:
                item.data.vertices.foreach_set("co", snapshots[frame_pos].ravel())
                item.data.update()
            still(scene, output / f"pilot-{name}-{frame:03}.png")
        for obj, _ in flat:
            bpy.data.objects.remove(obj, do_unlink=True)
    dump(output / "GEOMETRY_QA.json", {"run_id": native["run_id"], "frames": FRAMES, "continuity_states": 111,
         "method": "Authored LBS vs three Taubin iterations, 2 mm cap and smooth 15–35 mm endpoint protection.",
         "reference": "Saved model pathway endpoints, no registered independent anatomical footprint.",
         "volume": "computed only for welded and closed consistently oriented topology",
         "outside_attachment_proxy": "triangle centroid is greater than 15 mm from either source endpoint",
         "geometry_cpu_s": duration, "whole_body_bottom_baseline": whole_bottom,
         "baked_five_frame_glb_bytes": sizes, "pieces": report})
    print("Geometry QA completed across 111 states and rendered both methods at five exact frames.", flush=True)


if __name__ == "__main__":
    mode, *args = sys.argv[sys.argv.index("--") + 1:]
    {"build": overlay, "reopen": reopen, "render": render, "pilot": pilot,
     "regions": regions, "dq": dual_quaternion}[mode](*(Path(a) for a in args))
