"""Trusted headless Blender entrypoint. Input paths are assigned only by the worker."""

import json
import hashlib
import os
from pathlib import Path
import runpy
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

_CONNECTORS = []


def matrix(rotation, position):
    out = Matrix(rotation).to_4x4()
    out.translation = Vector(position)
    return out


def geom_object(geom):
    for name in ("Mesh_" + geom["usd_name"], "Mesh_Xform_" + geom["usd_name"]):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            return obj
    raise ValueError("imported geometry missing: " + geom["usd_name"])


def validate_import(expected):
    worst_position = worst_rotation = worst_landmark = worst_body = 0.0
    records = []
    for frame in expected["frames"]:
        bpy.context.scene.frame_set(frame["frame"])
        bpy.context.view_layer.update()
        for geom in frame["geoms"]:
            obj = geom_object(geom).evaluated_get(bpy.context.evaluated_depsgraph_get())
            actual = obj.matrix_world
            position = max(abs(actual[i][3] - geom["position_m"][i]) for i in range(3))
            rotation = max(abs(actual[i][j] - geom["rotation"][i][j]) for i in range(3) for j in range(3))
            worst_position = max(worst_position, position)
            worst_rotation = max(worst_rotation, rotation)
            if position > 2e-6 or rotation > 2e-6:
                raise ValueError(
                    f"geometry/time/coordinate mismatch: frame={frame['frame']} geom={geom['name']}, position={position}, rotation={rotation}"
                )
            if "surface" in geom:
                surface = geom["surface"]
                triangles = [
                    tuple(sorted(p.vertices)) for p in obj.data.polygons if len(set(p.vertices)) == 3
                ]
                coordinates = np.empty(len(obj.data.vertices) * 3, dtype="<f4")
                obj.data.vertices.foreach_get("co", coordinates)
                coordinates[coordinates == 0] = 0
                if hashlib.sha256(coordinates.tobytes()).hexdigest() != surface["vertex_coordinates_sha256"]:
                    raise ValueError("source mesh vertices changed: " + geom["name"])
                actual_hash = hashlib.sha256(
                    json.dumps(sorted(set(triangles)), separators=(",", ":")).encode()
                ).hexdigest()
                if (
                    len(obj.data.vertices) != surface["vertices"]
                    or actual_hash != surface["canonical_faces_sha256"]
                ):
                    raise ValueError("nondegenerate mesh surface changed during USD import: " + geom["name"])
            for landmark in geom.get("landmarks", []):
                point = actual @ obj.data.vertices[landmark["vertex"]].co
                delta = (point - Vector(landmark["world_m"])).length
                worst_landmark = max(worst_landmark, delta)
                if delta > 3e-6:
                    raise ValueError("mesh landmark/scale mismatch: " + geom["name"])
            if "body" in geom:
                body = geom["body"]
                local = matrix(body["geom_local_rotation"], body["geom_local_position_m"])
                recovered = actual @ local.inverted()
                target = matrix(body["rotation"], body["position_m"])
                delta = max(abs(recovered[i][j] - target[i][j]) for i in range(3) for j in range(4))
                worst_body = max(worst_body, delta)
                if delta > 3e-6:
                    raise ValueError("recovered solver body frame differs: " + body["name"])
                if frame["frame"] in (0, len(expected["frames"]) // 2, len(expected["frames"]) - 1):
                    records.append(
                        {
                            "frame": frame["frame"],
                            "source_index": frame["source_index"],
                            "geom": geom["name"],
                            "body": body["name"],
                            "translation_error_m": position,
                            "rotation_matrix_error": rotation,
                            "recovered_body_matrix_error": delta,
                            "position_m": list(actual.translation),
                        }
                    )
    return {
        "status": "pass",
        "surface_topology": "native vertex counts and distinct nondegenerate triangle indices preserved; repeated-index/duplicate faces may be normalized by Blender",
        "max_translation_error_m": worst_position,
        "max_rotation_matrix_error": worst_rotation,
        "max_world_landmark_error_m": worst_landmark,
        "max_recovered_body_matrix_error": worst_body,
        "sampled_bone_records": records,
        "checked_frames": len(expected["frames"]),
    }


def bake_transforms(expected):
    objects = list(bpy.data.objects)
    tracks = {o.name: [] for o in objects}
    for frame in expected["frames"]:
        bpy.context.scene.frame_set(frame["frame"])
        bpy.context.view_layer.update()
        for obj in objects:
            tracks[obj.name].append(
                obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
            )
    for obj in objects:
        obj.parent = None
        obj.constraints.clear()
        obj.animation_data_clear()
        for modifier in list(obj.modifiers):
            if modifier.type == "MESH_SEQUENCE_CACHE":
                obj.modifiers.remove(modifier)
        obj.rotation_mode = "QUATERNION"
        for frame, pose in enumerate(tracks[obj.name]):
            obj.matrix_world = pose
            for key in ("location", "rotation_quaternion", "scale"):
                obj.keyframe_insert(data_path=key, frame=frame)
    return validate_import(expected)


def material(name, color, metallic=0.0, roughness=0.4):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1)
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Roughness"].default_value = roughness
    return mat


def keypose(obj, start, end, radius, frame):
    _CONNECTORS.append((frame, obj.name, tuple(start), tuple(end)))
    delta = Vector(end) - Vector(start)
    length = delta.length
    obj.location = (Vector(start) + Vector(end)) * 0.5
    obj.rotation_mode = "QUATERNION"
    if length > 1e-12:
        z = delta.normalized()
        helper = Vector((0, 1, 0)) if abs(z.y) < 0.9 else Vector((1, 0, 0))
        x = helper.cross(z).normalized()
        y = z.cross(x).normalized()
        obj.rotation_quaternion = Matrix((x, y, z)).transposed().to_quaternion()
    else:
        obj.rotation_quaternion = (1, 0, 0, 0)
    obj.scale = (radius, radius, max(length * 0.5, 1e-9))
    for key in ("location", "rotation_quaternion", "scale"):
        obj.keyframe_insert(data_path=key, frame=frame)


def cylinder(name, mat):
    # Thousands of path segments must not each trigger an operator/dependency-graph update.
    mesh = bpy.data.meshes.get("overlay_unit_cylinder")
    if mesh is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=1, depth=2)
        template = bpy.context.object
        mesh = template.data
        mesh.name = "overlay_unit_cylinder"
        bpy.data.objects.remove(template, do_unlink=True)
    obj = bpy.data.objects.new(name, mesh.copy())
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def arrow(name, mat):
    shaft = cylinder(name, mat)
    bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=1, radius2=0, depth=2)
    head = bpy.context.object
    head.name = name + "_head"
    head.data.materials.append(mat)
    return shaft, head


def keyarrow(pair, start, end, frame):
    delta = Vector(end) - Vector(start)
    length = delta.length
    for obj in pair:
        obj.hide_render = length < 1e-7
        obj.keyframe_insert(data_path="hide_render", frame=frame)
    keypose(pair[0], start, end, 0.005, frame)
    direction = delta.normalized() if length > 1e-12 else Vector((0, 0, 1))
    keypose(
        pair[1],
        Vector(end) - direction * min(0.04, length * 0.3),
        end,
        min(0.014, max(0.001, length * 0.12)),
        frame,
    )


def sphere(name, mat, radius):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=radius)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def overlays(expected):
    _CONNECTORS.clear()
    layers = expected["request"]["layers"]
    cinematic = expected["request"]["profile"] == "cinematic" and not expected.get("pushup", expected["scenario_id"] == "pushup")
    has_paths = any(f["paths"] for f in expected["frames"])
    cyan = material("COM / world position [m]", (0.05, 0.63, 0.73), 0.2)
    amber = material("Ground force [N]", (0.95, 0.38, 0.035), 0.25)
    blue = material("External support force [N]", (0.15, 0.38, 0.95), 0.15)
    axis_mat = material("Joint axis (explanatory)", (0.22, 0.72, 0.57))
    axis_objects = {}
    paths = {}
    centroid = None
    ground = assist = moment = load = None
    contacts = []
    if "center_of_mass" in layers:
        centroid = sphere("mass_weighted_COM", cyan, 0.023)
    if "contact_forces" in layers:
        ground = arrow("GRF_scale_0.0006_m_per_N", amber)
        if expected["frames"][0]["metrics"].get("assist_force_z_N") is not None:
            assist = arrow("external_support_scale_0.0006_m_per_N", blue)
        for i in range(max(len(f["contact"]["polygon_xy_m"]) for f in expected["frames"])):
            contacts.append(sphere("native_contact_point_" + str(i), amber, 0.007))
    moment_mat = material("Applied moment [N*m]", (0.68, 0.18, 0.65), 0.1)
    if "applied_moments" in layers:
        moment = arrow("applied_moment_scale_0.006_m_per_Nm", moment_mat)
    load_N = expected["model"].get("derivation", {}).get("downward_load_N", 0)
    if "contact_forces" in layers and load_N:
        load = arrow("external_load_scale_0.0006_m_per_N", moment_mat)
    path_materials = {}
    if has_paths:
        for frame in expected["frames"]:
            for j, path in enumerate(frame["paths"]):
                key = (path["tendon_id"], path.get("segment", j))
                if key in paths:
                    continue
                act = path["activation"]
                color = (0.62, 0.055, 0.035) if cinematic else (0.12 + 0.76 * act, 0.23, 0.8 - 0.68 * act)
                mat = path_materials.get(path["tendon_id"]) or material(
                    "path_" + str(key) + " activation [0,1]"
                    if not cinematic
                    else "path explanatory red " + str(key),
                    color,
                    0.15,
                    0.3,
                )
                path_materials[path["tendon_id"]] = mat
                obj = cylinder("native_tendon_path_" + str(key), mat)
                obj["source_actuator"] = path["actuator"]
                obj["regions"] = ",".join(path.get("regions", []))
                paths[key] = obj
    hand_forces, hand_moments, pads = {}, {}, {}
    if "hand_contacts" in layers:
        for side in "rl":
            hand_forces[side] = arrow("hand_" + side + "_force", amber)
            hand_moments[side] = arrow("hand_" + side + "_ground_moment", moment_mat)
        for pad in expected["frames"][0]["hand_pads"]:
            pads[pad["name"]] = sphere("mechanical_pad_" + pad["name"], cyan, pad["radius_m"])
    for frame in expected["frames"]:
        i = frame["frame"]
        bpy.context.scene.frame_set(i)
        if centroid:
            centroid.location = frame["com_world_m"]
            centroid.keyframe_insert(data_path="location", frame=i)
        if "joint_axes" in layers:
            for axis in frame["joint_axes"]:
                obj = axis_objects.get(axis["joint"])
                if obj is None:
                    obj = cylinder("axis_" + axis["joint"], axis_mat)
                    axis_objects[axis["joint"]] = obj
                origin = Vector(axis["origin_m"])
                direction = Vector(axis["world_axis"]) * 0.045
                keypose(obj, origin - direction, origin + direction, 0.002, i)
        if has_paths:
            for j, path in enumerate(frame["paths"]):
                key = (path["tendon_id"], path.get("segment", j))
                obj = paths[key]
                keypose(obj, path["start_m"], path["end_m"], path.get("display_radius_m", max(path["radius_m"], 0.001)), i)
                if not cinematic:
                    node = obj.data.materials[0].node_tree.nodes["Principled BSDF"]
                    a = path["activation"]
                    node.inputs["Base Color"].default_value = (0.12 + 0.76 * a, 0.23, 0.8 - 0.68 * a, 1)
                    node.inputs["Base Color"].keyframe_insert(data_path="default_value", frame=i)
            active = {(p["tendon_id"], p.get("segment", j)) for j, p in enumerate(frame["paths"])}
            for key, obj in paths.items():
                obj.hide_render = key not in active
                obj.keyframe_insert(data_path="hide_render", frame=i)
        if hand_forces:
            for hand in frame["hands"]:
                side = hand["side"]
                points = [Vector(c["position_m"]) * c["normal_force_N"] for c in hand["contacts"]]
                weight = sum(c["normal_force_N"] for c in hand["contacts"])
                origin = sum(points, Vector()) / weight if weight > 1e-6 else Vector(hand["wrist_origin_m"])
                keyarrow(hand_forces[side], origin, origin + Vector(hand["force_world_N"]) * .0006, i)
                origin = Vector(hand["wrist_origin_m"])
                keyarrow(hand_moments[side], origin, origin + Vector(hand["ground_moment_about_wrist_Nm"]) * .006, i)
            for pad in frame["hand_pads"]:
                obj = pads[pad["name"]]
                obj.location = pad["position_m"]
                obj.keyframe_insert(data_path="location", frame=i)
        if ground:
            contact = frame["contact"]
            row = frame["metrics"]
            cop = contact["cop_xy_m"]
            start = [cop[0], cop[1], 0.002] if cop else [0, 0, 0.002]
            force = Vector([float(row["grf_" + a + "_N"]) for a in "xyz"])
            keyarrow(ground, start, Vector(start) + 0.0006 * force, i)
            if assist:
                start = Vector(frame["pelvis_com_world_m"])
                force = Vector([float(row["assist_force_" + a + "_N"]) for a in "xyz"])
                keyarrow(assist, start, start + 0.0006 * force, i)
            if load:
                start = Vector(frame["pelvis_com_world_m"])
                keyarrow(load, start, start + Vector((0, 0, -0.0006 * load_N)), i)
            points = contact["polygon_xy_m"]
            for j, obj in enumerate(contacts):
                obj.hide_render = j >= len(points)
                obj.keyframe_insert(data_path="hide_render", frame=i)
                if j < len(points):
                    obj.location = (*points[j], 0.003)
                    obj.keyframe_insert(data_path="location", frame=i)

        if moment:
            row = frame["metrics"]
            if "applied_torque_Nm" in row:
                axis = frame["joint_axes"][0]
                start = Vector(axis["origin_m"])
                vector = Vector(axis["world_axis"]) * float(row["applied_torque_Nm"])
            else:
                start = Vector(frame["pelvis_com_world_m"])
                vector = Vector([float(row["assist_torque_" + a + "_Nm"]) for a in "xyz"])
            keyarrow(moment, start, start + 0.006 * vector, i)


def validate_path_visibility(expected):
    counts = []
    for frame in expected["frames"]:
        bpy.context.scene.frame_set(frame["frame"])
        bpy.context.view_layer.update()
        active = {"native_tendon_path_" + str((p["tendon_id"], p.get("segment", j))) for j, p in enumerate(frame["paths"])}
        visible = {
            o.name for o in bpy.data.objects if o.name.startswith("native_tendon_path_") and not o.hide_render
        }
        if active != visible:
            raise ValueError("Missing or ghost tendon path segments at frame " + str(frame["frame"]))
        counts.append(len(visible))
    return {"status": "pass", "checked_frames": len(counts), "visible_native_segments": counts}


def validate_connectors(expected):
    by_frame = {}
    for frame, name, start, end in _CONNECTORS:
        by_frame.setdefault(frame, []).append((name, start, end))
    maximum = 0.0
    for frame in expected["frames"]:
        bpy.context.scene.frame_set(frame["frame"])
        bpy.context.view_layer.update()
        for name, start, end in by_frame.get(frame["frame"], []):
            obj = bpy.data.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get())
            for local, target in (((0, 0, -1), start), ((0, 0, 1), end)):
                delta = (obj.matrix_world @ Vector(local) - Vector(target)).length
                maximum = max(maximum, delta)
                if delta > 3e-6:
                    raise ValueError(
                        f"Overlay endpoint mismatch at frame {frame['frame']} / {name}: {delta} m"
                    )
    return {
        "status": "pass",
        "checked_segments": len(_CONNECTORS),
        "checked_frames": len(expected["frames"]),
        "max_endpoint_error_m": maximum,
        "tolerance_m": 3e-6,
    }


def atlas_overlay(expected):
    if "atlas" not in expected:
        return None
    atlas, frames = expected["atlas"], expected["frames"]
    faces = atlas["faces"]
    mesh = bpy.data.meshes.new("BodyParts3D FJ1447")
    mesh.from_pydata(frames[0]["atlas_vertices_m"], [], faces)
    if mesh.validate(verbose=True):
        raise ValueError("Blender changed imported atlas topology")
    mesh.update()
    obj = bpy.data.objects.new("atlas_pectoralis_right_clavicular", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["source_notice"] = json.dumps(atlas["source"], ensure_ascii=False)
    obj["interpretation"] = "Illustrative skinning; activation mapping unavailable"
    default_material = runpy.run_path(str(Path(__file__).with_name("muscle_materials.py")))
    default_material["apply"](mesh)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj.shape_key_add(name="Basis")
    for frame in frames[1:]:
        index = frame["frame"]
        key = obj.shape_key_add(name=f"Saved state {frame['source_index']}")
        key.data.foreach_set("co", np.asarray(frame["atlas_vertices_m"], dtype=np.float32).ravel())
        for position, weight in ((0, 0), (index - 1, 0), (index, 1), (index + 1, 0)):
            key.value = weight
            key.keyframe_insert(data_path="value", frame=position)
    results = []
    scene = bpy.context.scene
    for frame in frames:
        scene.frame_set(frame["frame"])
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        evaluated.data.vertices.foreach_get("co", coordinates)
        coordinates = coordinates.reshape(-1, 3)
        error = float(np.max(np.linalg.norm(coordinates - np.asarray(frame["atlas_vertices_m"]), axis=1)))
        if error > 3e-6 or [list(p.vertices) for p in evaluated.data.polygons] != faces:
            raise ValueError("Blender evaluated atlas surface differs from registered geometry")
        surface = BVHTree.FromPolygons(coordinates, faces, all_triangles=True)
        touching = {}
        for geom in frame["geoms"]:
            if geom["name"] in {"clavicle", "humerus", "scapula"}:
                bone = geom_object(geom).evaluated_get(depsgraph)
                bone_surface = BVHTree.FromPolygons(
                    [bone.matrix_world @ vertex.co for vertex in bone.data.vertices],
                    [list(face.vertices) for face in bone.data.polygons],
                )
                touching[geom["name"]] = len(surface.overlap(bone_surface))
        results.append({"frame": frame["frame"], "source_index": frame["source_index"],
                        "max_vertex_error_m": error, "bone_triangle_crossings": touching})
    scene.frame_set(0)
    return {"status": "PASS", "vertex_tolerance_m": 3e-6, "frames": results,
            "display_material": {"texture": "procedural fibres", "coordinates": "fixed mesh coordinates"},
            "intersection_method": "Blender BVH triangle crossings; does not measure enclosed tissue or attachment correctness"}


def setup_scene(expected):
    scene = bpy.context.scene
    options = expected["request"]["options"]
    cinematic = expected["request"]["profile"] == "cinematic"
    bone = material(
        "Native model bone / presentation material",
        (0.72, 0.62, 0.43) if cinematic else (0.67, 0.72, 0.73),
        0.15 if cinematic else 0.02,
        0.28 if cinematic else 0.5,
    )
    other = material("Native non-bone geometry / presentation material", (0.18, 0.23, 0.27), 0.05, 0.55)
    if expected.get("pushup", expected["scenario_id"] == "pushup"):
        other = material("Pushup studio floor", (.025, .04, .06), 0, .8)
    allowed = {"Mesh_" + g["usd_name"] for f in expected["frames"] for g in f["geoms"]}
    show_base = bool({"bones", "native_geometry"} & set(expected["request"]["layers"]))
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.hide_render = not (show_base and obj.name in allowed or "floor_id" in obj.name)
            obj.data.materials.clear()
            obj.data.materials.append(bone if "floor" not in obj.name else other)
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
    contact = expected["model"]["id"] == "ms_human_700_locomotion"
    region_points = []
    if expected.get("pushup", expected["scenario_id"] == "pushup"):
        target = Vector((.72, 0, .04))
        eye = target + Vector((1.6, -3.3, 1.35))
        lens = 44
        view = options.get("camera_view", "full_body")
        if view == "hands":
            positions = [h["position_m"] for h in expected["frames"][0]["hand_pads"]]
            if not positions:
                raise ValueError("hand camera requires a palms/knuckles run with wrist measurements")
            # Keep both hand contacts above the lower-third numeric plots.
            target = Vector(np.mean(positions, axis=0)) + Vector((0, 0, -.1))
            extent = max(1., float(np.linalg.norm(np.ptp(positions, axis=0)[:2])) / .6)
            eye, lens = target + Vector((.65, -1.1, .6)) * extent, 52
        elif view in ("lumbar", "abdomen", "chest"):
            region = expected.get("regional_layer") or ("lumbar_muscles" if view == "lumbar" else "abdominal_muscles")
            region_points = [p[key] for f in expected["frames"] for p in f["paths"]
                             if region in p.get("regions", []) for key in ("start_m", "end_m")]
            if "atlas" in expected and view == "chest":
                region_points = [point for f in expected["frames"] for point in f["atlas_vertices_m"]]
            target = Vector(np.mean([f["pelvis_com_world_m"] for f in expected["frames"]], axis=0)) + Vector((.15, 0, -.03))
            direction = Vector((.32, -1.1, -.35 if "atlas" in expected else .7 if view == "lumbar" else -.04)).normalized()
            distance, lens = 1.8, 52
            if region_points:
                points = np.array(region_points)
                target = Vector((points.min(axis=0) + points.max(axis=0)) / 2)
                right = Vector((0, 0, 1)).cross(direction).normalized()
                up = direction.cross(right).normalized()
                relative = points - np.array(target)
                depth = relative @ np.array(direction)
                tan_x = 36 / (2 * lens)
                tan_y = tan_x * options["height"] / options["width"]
                distance = max(.62 if "atlas" in expected else .9, float(np.max(abs(relative @ np.array(right)) / (.9 * tan_x) + depth)),
                               float(np.max(abs(relative @ np.array(up)) / (.72 * tan_y) + depth)))
            eye = target + direction * distance
        elif expected["model"].get("derivation", {}).get("hand_support", "legacy_point") != "legacy_point":
            target = Vector((.9, 0, .04))
            eye, lens = target + Vector((1.6, -3.3, 1.35)), 42
        if view == "full_body" and expected["request"].get("recipe") == "pushup_scientific":
            offset = Vector((0, 0, .20))
            target += offset
            eye += offset
    elif contact:
        target = Vector((0, 0, 0.88))
        eye = Vector((2.5, -4.0, 1.65))
        lens = 48
    else:
        anchor = expected["frames"][0]["joint_axes"][0]["origin_m"]
        target = Vector(anchor) + Vector((0, 0, 0.12))
        eye = target + Vector((1.8, -2.8, 0.4))
        lens = 58
    bpy.ops.object.camera_add(location=eye)
    camera = bpy.context.object
    camera.name = "fixed_scientific_camera"
    camera.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = lens
    camera.data.clip_start = 0.01
    camera.data.clip_end = 100
    scene.camera = camera
    framing = None
    if region_points:
        from bpy_extras.object_utils import world_to_camera_view
        scene.render.resolution_x, scene.render.resolution_y = options["width"], options["height"]
        scene.render.resolution_percentage = 100
        camera.data.sensor_fit = "HORIZONTAL"
        bpy.context.view_layer.update()
        projected = [world_to_camera_view(scene, camera, Vector(p)) for p in region_points]
        if not all(.04 <= p.x <= .96 and .1 <= p.y <= .9 and p.z > 0 for p in projected):
            raise ValueError("regional camera loses selected paths during saved motion")
        framing = {"status": "pass", "checked_path_endpoints": len(projected),
                   "screen_x_range": [min(p.x for p in projected), max(p.x for p in projected)],
                   "screen_y_range": [min(p.y for p in projected), max(p.y for p in projected)]}
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    world = bpy.data.worlds.new("Scientific studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.075, 0.095, 0.13, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    scene.world = world
    for name, offset, power, size in [
        ("key", (2, -3, 4), 1100, 4),
        ("fill", (-3, -1, 2), 650, 3),
        ("rim", (1, 3, 3), 1400, 2),
    ]:
        bpy.ops.object.light_add(type="AREA", location=target + Vector(offset))
        light = bpy.context.object
        light.name = "studio_" + name
        light.data.energy = power * (1.2 if cinematic else 1)
        if expected.get("pushup", expected["scenario_id"] == "pushup"):
            light.data.energy *= .45
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = options["samples"]
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.cycles.transparent_max_bounces = 4
    scene.render.resolution_x = options["width"]
    scene.render.resolution_y = options["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.fps = options["fps"]
    scene.frame_start = 0
    scene.frame_end = len(expected["frames"]) - 1
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return {
        "position_m": list(camera.location),
        "target_m": list(target),
        "rotation_euler_rad": list(camera.rotation_euler),
        "lens_mm": lens,
        "scale_length": 1,
        "world_up": "Z",
        "regional_path_framing": framing,
    }


def select_device(requested):
    if requested == "cpu":
        bpy.context.scene.cycles.device = "CPU"
        return {"backend": "cpu", "devices": ["CPU"]}
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            devices = [d for d in prefs.devices if d.type == backend]
            if devices:
                for d in prefs.devices:
                    d.use = d.type == backend
                bpy.context.scene.cycles.device = "GPU"
                return {"backend": backend.lower(), "devices": [d.name for d in devices]}
        except Exception:
            continue
    bpy.context.scene.cycles.device = "CPU"
    return {
        "backend": "cpu_fallback",
        "devices": ["CPU"],
        "fallback_reason": "No usable Cycles CUDA/OptiX device enumerated",
    }


def prepare_scene(path, expected):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.usd_import(
        filepath=str(path / "work" / expected["usd_file"]),
        import_cameras=False,
        import_lights=False,
        import_materials=False,
        scale=1.0,
        read_mesh_uvs=False,
        read_mesh_colors=False,
    )
    imported = validate_import(expected)
    baked = bake_transforms(expected)
    bpy.context.scene.frame_set(0)
    camera = setup_scene(expected)
    overlays(expected)
    atlas = atlas_overlay(expected)
    if expected.get("pushup", expected["scenario_id"] == "pushup"):
        collections = {}
        for obj in list(bpy.context.scene.objects):
            group = ("pectoralis_atlas" if obj.name.startswith("atlas_pectoralis_") else
                     "muscle_paths" if obj.name.startswith("native_tendon_path_") else
                     "joint_axes" if obj.name.startswith("axis_") else
                     "contact_forces" if obj.name.startswith(("GRF_", "native_contact_point_")) else
                     "center_of_mass" if obj.name == "mass_weighted_COM" else
                     "bones" if obj.name.startswith("Mesh_") and "floor" not in obj.name else "studio")
            if group == "muscle_paths" and obj.get("regions"):
                memberships = obj["regions"].split(",")
                group = next((r for r in ("hand_tendons", "pectoral_muscles", "abdominal_muscles", "lumbar_muscles", "arm_muscles") if r in memberships), group)
            elif obj.name.startswith(("hand_", "mechanical_pad_")):
                group = "hand_contacts"
            if group not in collections:
                collection = bpy.data.collections.new(group)
                bpy.context.scene.collection.children.link(collection)
                collections[group] = collection
            for collection in list(obj.users_collection):
                collection.objects.unlink(obj)
            collections[group].objects.link(obj)
    paths = validate_path_visibility(expected)
    connectors = validate_connectors(expected)
    return imported, baked, camera, atlas, paths, connectors


def main():
    started = time.monotonic()
    path = Path(sys.argv[sys.argv.index("--") + 1])
    expected = json.loads((path / "work/expected.json").read_text())
    imported, baked, camera, atlas, paths, connectors = prepare_scene(path, expected)
    device = select_device(os.environ.get("HMM_BLENDER_DEVICE", expected["request"]["options"]["device"]))
    # Explicit host-controlled fault injection; never accepted from MCP/render parameters.
    fault = os.environ.get("HMM_TEST_RENDER_FAILURE")
    if fault == "timeout":
        time.sleep(60)
    if fault == "crash":
        raise RuntimeError("injected Blender process failure")
    if fault == "oom" and device["backend"] in ("cuda", "optix"):
        raise MemoryError("injected GPU out of memory before allocation")
    artifacts = path / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def write(name, value):
        (artifacts / name).write_text(json.dumps(value, indent=2) + "\n")

    write(
        "geometry_validation.json",
        {
            "imported_usd": imported,
            "baked_blend": baked,
            "native_path_visibility": paths,
            "overlay_connectors": connectors,
            **({"atlas_surface": atlas} if atlas else {}),
        },
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(artifacts / "scene.blend"), compress=True)
    for frame in expected["frames"]:
        bpy.context.scene.frame_set(frame["frame"])
        bpy.context.scene.render.filepath = str(path / "work" / f"raw_{frame['frame']:04d}.png")
        bpy.ops.render.render(write_still=True)
        (path / "progress.json").write_text(
            json.dumps(
                {
                    "phase": "cycles",
                    "completed_frames": frame["frame"] + 1,
                    "total_frames": len(expected["frames"]),
                }
            )
        )
    write(
        "blender_render.json",
        {
            "status": "rendered",
            "blender_version": bpy.app.version_string,
            "blender_build_hash": bpy.app.build_hash.decode(),
            "device": device,
            "camera": camera,
            "render_seconds": time.monotonic() - started,
            "cycles_samples": bpy.context.scene.cycles.samples,
            "cycles_seed": 0,
            "cycles_max_bounces": bpy.context.scene.cycles.max_bounces,
            "denoising": bpy.context.scene.cycles.use_denoising,
            "lighting": [
                {
                    "name": o.name,
                    "position_m": list(o.location),
                    "rotation_euler_rad": list(o.rotation_euler),
                    "type": o.data.type,
                    "power_W": o.data.energy,
                    "size_m": o.data.size,
                }
                for o in bpy.context.scene.objects
                if o.type == "LIGHT"
            ],
            "world_background": {"linear_rgb": [0.075, 0.095, 0.13], "strength": 0.35},
            "color_management": "AgX; exposure 0; gamma 1",
            "physics": "not_executed",
            "materials": "presentation only; scientific paths use saved dimensionless activation linear blue-red [0,1]; cinematic red is explanatory",
            "force_scale_m_per_N": 0.0006,
            "moment_scale_m_per_Nm": 0.006,
            "display_path_min_radius_m": min((p.get("display_radius_m", max(p["radius_m"], .001)) for f in expected["frames"] for p in f["paths"]), default=None),
            "display_path_radius_interpretation": "Presentation thickness for source transmission paths; not measured muscle or tendon cross-section",
            "moment_interpretation": "Elbow generalized hinge torque or pelvis external world moment pseudovector; not a joint reaction estimate",
            "joint_axis_half_length_m": 0.045,
            "saved_scene": "Baked native object transforms; no external USD cache dependency",
        },
    )


if __name__ == "__main__":
    main()
