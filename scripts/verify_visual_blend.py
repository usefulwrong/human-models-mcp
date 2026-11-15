"""Read the downloaded standalone .blend and reject bad scale, axes and frame clock."""

import bpy
import json
import sys
from pathlib import Path
from mathutils import Vector

folder = Path(sys.argv[sys.argv.index("--") + 1])
expected = json.loads((folder / "unpacked/scene/expected.json").read_text())


def load():
    bpy.ops.wm.open_mainfile(filepath=str(folder / "scene.blend"), load_ui=False)


def validate_overlays(frame, mapping):
    layers = mapping["request"]["layers"]
    error = 0.0

    def point(actual, target):
        nonlocal error
        delta = (Vector(actual) - Vector(target)).length
        error = max(error, delta)
        if delta > 3e-6:
            raise ValueError("overlay geometry/units mismatch")

    def segment(name, start, end):
        obj = bpy.data.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get())
        point(obj.matrix_world @ Vector((0, 0, -1)), start)
        point(obj.matrix_world @ Vector((0, 0, 1)), end)

    if "center_of_mass" in layers:
        point(bpy.data.objects["mass_weighted_COM"].matrix_world.translation, frame["com_world_m"])
    if "joint_axes" in layers:
        for axis in frame["joint_axes"]:
            o, d = Vector(axis["origin_m"]), Vector(axis["world_axis"]) * 0.045
            segment("axis_" + axis["joint"], o - d, o + d)
    if frame["paths"]:
        view = mapping["request"]["options"].get("camera_view")
        if view in ("lumbar", "abdomen", "chest"):
            from bpy_extras.object_utils import world_to_camera_view
            region = mapping.get("regional_layer") or ("lumbar_muscles" if view == "lumbar" else "abdominal_muscles")
            for path in frame["paths"]:
                if region not in path.get("regions", []):
                    continue
                for key in ("start_m", "end_m"):
                    p = world_to_camera_view(bpy.context.scene, bpy.context.scene.camera, Vector(path[key]))
                    if not (.04 <= p.x <= .96 and .1 <= p.y <= .9 and p.z > 0):
                        raise ValueError("regional paths outside camera view")
        active = {"native_tendon_path_" + str((p["tendon_id"], p.get("segment", j))) for j, p in enumerate(frame["paths"])}
        visible = {
            o.name for o in bpy.data.objects if o.name.startswith("native_tendon_path_") and not o.hide_render
        }
        if active != visible:
            raise ValueError("missing or ghost tendon segments: visibility does not match native frame")
        for j, path in enumerate(frame["paths"]):
            name = "native_tendon_path_" + str((path["tendon_id"], path.get("segment", j)))
            segment(name, path["start_m"], path["end_m"])
            if mapping["request"]["profile"] != "cinematic" or mapping.get("pushup"):
                color = (
                    bpy.data.objects[name]
                    .data.materials[0]
                    .node_tree.nodes["Principled BSDF"]
                    .inputs["Base Color"]
                    .default_value
                )
                a = path["activation"]
                if max(abs(x - y) for x, y in zip(color, (0.12 + 0.76 * a, 0.23, 0.8 - 0.68 * a, 1))) > 1e-6:
                    raise ValueError("activation color differs from saved dimensionless activation")
    row = frame["metrics"]
    if "hand_contacts" in layers:
        for pad in frame["hand_pads"]:
            point(bpy.data.objects["mechanical_pad_" + pad["name"]].matrix_world.translation, pad["position_m"])
        for hand in frame["hands"]:
            weight = sum(c["normal_force_N"] for c in hand["contacts"])
            origin = sum((Vector(c["position_m"]) * c["normal_force_N"] for c in hand["contacts"]), Vector()) / weight if weight > 1e-6 else Vector(hand["wrist_origin_m"])
            segment("hand_" + hand["side"] + "_force", origin, origin + Vector(hand["force_world_N"]) * .0006)
            origin = Vector(hand["wrist_origin_m"])
            segment("hand_" + hand["side"] + "_ground_moment", origin, origin + Vector(hand["ground_moment_about_wrist_Nm"]) * .006)
    if "contact_forces" in layers:
        cop = frame["contact"]["cop_xy_m"]
        start = Vector((cop[0], cop[1], 0.002) if cop else (0, 0, 0.002))
        force = Vector([float(row["grf_" + a + "_N"]) for a in "xyz"])
        segment("GRF_scale_0.0006_m_per_N", start, start + force * 0.0006)
        if "assist_force_z_N" in row:
            start = Vector(frame["pelvis_com_world_m"])
            force = Vector([float(row["assist_force_" + a + "_N"]) for a in "xyz"])
            segment("external_support_scale_0.0006_m_per_N", start, start + force * 0.0006)
    if "applied_moments" in layers:
        if "applied_torque_Nm" in row:
            axis = frame["joint_axes"][0]
            start = Vector(axis["origin_m"])
            moment = Vector(axis["world_axis"]) * float(row["applied_torque_Nm"])
        else:
            start = Vector(frame["pelvis_com_world_m"])
            moment = Vector([float(row["assist_torque_" + a + "_Nm"]) for a in "xyz"])
        segment("applied_moment_scale_0.006_m_per_Nm", start, start + moment * 0.006)
    return error


def validate(mapping):
    maxp = maxr = maxv = max_overlay = 0.0
    positions = []
    for index in range(len(mapping["frames"])):
        source = mapping["frames"][index]
        bpy.context.scene.frame_set(source["frame"])
        bpy.context.view_layer.update()
        max_overlay = max(max_overlay, validate_overlays(source, mapping))
        for g in source["geoms"]:
            if "landmarks" not in g:
                continue
            obj = bpy.data.objects["Mesh_" + g["usd_name"]].evaluated_get(
                bpy.context.evaluated_depsgraph_get()
            )
            m = obj.matrix_world
            show_base = bool({"bones", "native_geometry"} & set(mapping["request"]["layers"]))
            if bpy.data.objects["Mesh_" + g["usd_name"]].hide_render == show_base:
                raise ValueError("native layer visibility mismatch")
            p = max(abs(m[a][3] - g["position_m"][a]) for a in range(3))
            r = max(abs(m[a][b] - g["rotation"][a][b]) for a in range(3) for b in range(3))
            maxp = max(maxp, p)
            maxr = max(maxr, r)
            if p > 2e-6 or r > 2e-6:
                raise ValueError("pose/clock mismatch")
            for landmark in g["landmarks"]:
                delta = (m @ obj.data.vertices[landmark["vertex"]].co - Vector(landmark["world_m"])).length
                maxv = max(maxv, delta)
                if delta > 3e-6:
                    raise ValueError("geometry/scale/axis mismatch")
            positions.append({"frame": index, "bone": g["name"], "position": list(m.translation)})
    return {
        "max_translation_error_m": maxp,
        "max_rotation_matrix_error": maxr,
        "max_world_landmark_error_m": maxv,
        "max_overlay_endpoint_error_m": max_overlay,
        "overlays_checked": mapping["request"]["layers"],
        "positions": positions,
    }


load()
positive = validate(expected)
negatives = {}
geom = next(g for g in expected["frames"][0]["geoms"] if "landmarks" in g)
for fault in ("wrong_scale", "wrong_axis", "dropped_frame"):
    load()
    mapping = json.loads(json.dumps(expected))
    if fault == "dropped_frame":
        mapping["frames"][len(mapping["frames"]) // 2]["frame"] = 0
    else:
        obj = bpy.data.objects["Mesh_" + geom["usd_name"]]
        for vertex in obj.data.vertices:
            if fault == "wrong_scale":
                vertex.co *= 100
            else:
                vertex.co = Vector((vertex.co.x, -vertex.co.z, vertex.co.y))
        obj.data.update()
    try:
        validate(mapping)
    except ValueError as exc:
        negatives[fault] = {"status": "detected", "message": str(exc)}
    else:
        raise AssertionError("broken mapping was not detected: " + fault)
result = {
    "status": "pass",
    "positive": positive,
    "negative_mappings": negatives,
    "standalone_scene": "Downloaded scene read with original export work directory unavailable",
    "blender_version": bpy.app.version_string,
}
(folder / "independent-blend.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
