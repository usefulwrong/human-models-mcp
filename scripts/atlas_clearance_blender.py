"""Experimental directional clearance for superficial atlas torso surfaces."""

import json
from pathlib import Path
import sys

import bpy
import numpy as np

from atlas_collision_blender import ATLAS, bone_surfaces, check_detector, frame_collisions, intersections, surface


MAX_SHIFT_M = .024
PECTORAL = {"clavicular": "PECM1", "sternocostal": "PECM2", "abdominal": "PECM3"}


def normalized(vector):
    norm = np.linalg.norm(vector)
    if norm <= 1e-6:
        raise ValueError("degenerate surface correction direction")
    return vector / norm


def axes(frame):
    left, right = (np.asarray(frame["rectus_sites_m"][side]) for side in ("l", "r"))
    superior = normalized((left[-1] + right[-1]) - (left[0] + right[0]))
    lateral = left[-1] - right[-1]
    lateral = normalized(lateral - superior * np.dot(lateral, superior))
    anterior = normalized(np.cross(lateral, superior))
    return (left[0] + right[0]) / 2., superior, lateral, anterior


def selected_objects(scene):
    return [
        obj for obj in scene.collection.children[ATLAS].all_objects
        if obj.type == "MESH" and (
            "pectoralis major" in obj.get("source_label", "").lower()
            or "external oblique" in obj.get("source_label", "").lower()
            or "trapezius" in obj.get("source_label", "").lower()
        )
    ]


def adjusted_surface(label, points, source, context):
    origin, superior, lateral, anterior = axes(source)
    sign = 1. if "left" in label else -1.
    if "pectoralis major" in label:
        actuator = PECTORAL[label.split()[0]] + ("_l" if sign > 0 else "_r")
        paths = [path for path in context["paths"] if path["actuator"] == actuator]
        if not paths:
            raise ValueError("saved pectoral anchor paths missing")
        anchors = np.asarray([paths[0]["start_m"], paths[-1]["end_m"]])
        distance = np.linalg.norm(points[:, None] - anchors, axis=2).min(axis=1)
        weight = ((distance - .01) / .065).clip(0, 1)
        direction = normalized(anterior + .4 * sign * lateral)
    elif "external oblique" in label:
        # Keep the inferior attachment region near the pelvis fixed.
        weight = (((points - origin) @ superior - .010) / .10).clip(0, 1)
        direction = normalized(anterior + .8 * sign * lateral)
    else:
        # Keep the medial strip near the thoracic spinous processes fixed.
        weight = ((abs((points - origin) @ lateral) - .025) / .04).clip(0, 1)
        direction = -anterior
    return points + MAX_SHIFT_M * weight[:, None] * direction, weight


def bake_surface(obj, collection, frames, poses):
    mesh = obj.data.copy()
    fitted = bpy.data.objects.new(obj.name + " · fitted", mesh)
    fitted["source_label"] = obj["source_label"]
    collection.objects.link(fitted)
    if mesh.shape_keys:
        fitted.shape_key_clear()
    mesh.vertices.foreach_set("co", poses[0].ravel())
    mesh.update()
    fitted.shape_key_add(name="Basis")
    for i, pose in zip(frames[1:], poses[1:], strict=True):
        key = fitted.shape_key_add(name=f"Saved sample {i}")
        key.data.foreach_set("co", pose.ravel())
        for index, weight in ((0, 0), (i - 1, 0), (i, 1), (i + 1, 0)):
            key.value = weight
            key.keyframe_insert(data_path="value", frame=index)
    return fitted


def transfer(scene, output, expected, binding, preview):
    check_detector()
    muscles = selected_objects(scene)
    if len(muscles) != 12:
        raise ValueError(f"expected twelve named bilateral superficial surfaces, found {len(muscles)}")
    frames = [scene.frame_start, scene.frame_end // 2, scene.frame_end] if preview else list(range(scene.frame_end + 1))
    scene_collection = scene.collection.children
    baked = scene_collection[ATLAS]
    corrections = bpy.data.collections.new("Superficial torso · clearance fit")
    saved = bpy.data.collections.new("Original surfaces · retained for comparison")
    baked.children.link(corrections)
    baked.children.link(saved)
    fit_layers = {}
    for name in ("Pectoralis major", "External obliques", "Trapezius"):
        layer = bpy.data.collections.new(name)
        corrections.children.link(layer)
        fit_layers[name] = layer
    per_frame = {}
    mesh_samples = {obj.name: [] for obj in muscles}
    for i in frames:
        scene.frame_set(i)
        bpy.context.view_layer.update()
        source = binding["frames"][i]
        context = expected["frames"][i]
        if source["state_sha256"] != context["state_sha256"]:
            raise ValueError("collision correction inputs refer to different saved states")
        graph = bpy.context.evaluated_depsgraph_get()
        bones = bone_surfaces(scene_collection["bones"].objects, graph)
        result = {}
        for obj in muscles:
            points, triangles = surface(obj, graph)
            label = obj["source_label"]
            adjusted, weight = adjusted_surface(label.lower(), points, source, context)
            edge_indices = np.array([tuple(edge.vertices) for edge in obj.data.edges])
            begin, end = edge_indices.T
            before_length = np.linalg.norm(points[begin] - points[end], axis=1)
            after_length = np.linalg.norm(adjusted[begin] - adjusted[end], axis=1)
            nonzero = before_length > 1e-6
            ratios = after_length[nonzero] / before_length[nonzero]
            mesh_samples[obj.name].append(adjusted.astype(np.float32))
            result[label] = {
                "max_vertex_displacement_m": float(np.max(np.linalg.norm(points - adjusted, axis=1))),
                "fixed_attachment_region_vertices": int(np.count_nonzero(weight == 0)),
                "edge_length_ratio_p01_p99": np.quantile(ratios, [.01, .99]).tolist(),
                "triangle_intersections_before": intersections(points, triangles, bones),
            }
        per_frame[i] = {"source_index": source["index"], "meshes": result}

    corrected = []
    for obj in muscles:
        label = obj["source_label"].lower()
        group = ("Pectoralis major" if "pectoralis major" in label
                 else "External obliques" if "external oblique" in label else "Trapezius")
        fitted = bake_surface(obj, fit_layers[group], frames, mesh_samples[obj.name])
        fitted["correction"] = "Bounded superficial position adjustment; illustrative geometry"
        corrected.append(fitted)
        for group in list(obj.users_collection):
            group.objects.unlink(obj)
        saved.objects.link(obj)
    saved.hide_render = True
    bpy.context.view_layer.layer_collection.children[ATLAS].children[saved.name].hide_viewport = True
    for i in frames:
        after = frame_collisions(scene, i, corrected)
        for name, result in per_frame[i]["meshes"].items():
            result["triangle_intersections_after"] = after.get(name, {})
    nonimproving = [
        {"frame": i, "name": name}
        for i, record in per_frame.items()
        for name, result in record["meshes"].items()
        if sum(result["triangle_intersections_after"].values()) >= sum(result["triangle_intersections_before"].values())
    ]
    report = {"status": "REJECTED_NONIMPROVING_FIT" if nonimproving else "ILLUSTRATIVE_GEOMETRY_CORRECTION",
              "frames": per_frame, "nonimproving_mesh_frames": nonimproving, "three_frame_preview": preview,
              "max_allowed_displacement_m": MAX_SHIFT_M,
              "limitations": ["Surface intersection counts include attachment sites.",
                              "Correction is geometric and independent of muscle activation.",
                              "The fitted set is limited to pectoralis major, external oblique and trapezius."]}
    (output / "clearance.json").write_text(json.dumps(report, indent=2))
    if nonimproving:
        raise ValueError("superficial fit did not reduce bone crossings in every fitted mesh/frame")
    scene.frame_set(0)
    note = bpy.data.texts.new("Superficial clearance · evidence")
    note.write("Illustrative fit of twelve candidate surfaces. The archived original geometries are in the same atlas collection. Residual intersections remain. See clearance.json for the saved-state checks.")
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "clearance.blend"), compress=True)


if __name__ == "__main__":
    dest, expected_path, binding_path, *mode = sys.argv[sys.argv.index("--") + 1:]
    transfer(bpy.context.scene, Path(dest), json.loads(Path(expected_path).read_text()),
             json.loads(Path(binding_path).read_text()), preview=mode == ["preview"])
