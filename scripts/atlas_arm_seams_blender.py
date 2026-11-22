"""Repair split atlas skin weights at exactly coincident upper-limb vertices."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_arm_review_blender import check_arm_bone_pose, path_muscles
from atlas_collision_blender import ATLAS, bone_surfaces, intersections, rendered_meshes, surface, tree


UPPER_LIMB = (
    "deltoid", "biceps brachii", "triceps brachii", "brachialis", "coracobrachialis",
    "brachioradialis", "anconeus", "pronator", "supinator", "extensor carpi",
    "flexor carpi", "palmaris longus", "extensor indicis", "extensor digitorum",
    "extensor digiti minimi", "flexor digitorum superficialis", "flexor digitorum profundus",
    "extensor pollicis", "flexor pollicis", "abductor pollicis", "adductor pollicis",
    "opponens pollicis", "interossei of", "lumbrical muscle of",
)


def duplicate_positions(obj):
    points = np.empty((len(obj.data.vertices), 3), dtype=np.float32)
    obj.data.vertices.foreach_get("co", points.ravel())
    _, inverse, counts = np.unique(points, axis=0, return_inverse=True, return_counts=True)
    return [np.flatnonzero(inverse == i).tolist() for i in np.flatnonzero(counts > 1)]


def profiles(obj, indices):
    return [
        {g.group: g.weight for g in obj.data.vertices[i].groups if g.weight > 0}
        for i in indices
    ]


def equalize(obj, groups):
    changed = 0
    for indices in groups:
        weights = profiles(obj, indices)
        if all(weight == weights[0] for weight in weights[1:]):
            continue
        keys = set().union(*(w.keys() for w in weights))
        averaged = {key: sum(w.get(key, 0.) for w in weights) / len(weights) for key in keys}
        normalizer = sum(averaged.values())
        if normalizer <= 0:
            raise ValueError("seam group contains no usable rig weight")
        for key, value in averaged.items():
            obj.vertex_groups[key].add(indices, value / normalizer, "REPLACE")
        changed += 1
    return changed


def seam_width(points, groups):
    maximum = 0.
    for indices in groups:
        group = points[indices]
        distances = np.linalg.norm(group[:, None] - group[None, :], axis=2)
        maximum = max(maximum, float(distances.max()))
    return maximum


def upper_limb_objects(scene):
    return [
        obj for obj in rendered_meshes(scene.collection.children[ATLAS])
        if any(term in obj.get("source_label", "").lower() for term in UPPER_LIMB)
        and not any(term in obj.get("source_label", "").lower() for term in
                    ("foot", "hallucis", "extensor digitorum longus", "extensor digitorum brevis"))
        and any(mod.type == "ARMATURE" for mod in obj.modifiers)
    ]


def trial(scene, output, expected, key_phases):
    frames = expected["frames"]
    if [frame["frame"] for frame in frames] != list(range(scene.frame_end + 1)):
        raise ValueError("seam inputs do not describe this Blender timeline")
    atlas = scene.collection.children[ATLAS]
    draft = bpy.data.collections.new("Upper limb · coincident seam fit")
    atlas.children.link(draft)
    paths = {obj.name: name for name, obj in path_muscles(scene).items()}
    pairs = []
    for obj in upper_limb_objects(scene):
        groups = duplicate_positions(obj)
        adjusted = obj.copy()
        adjusted.data = obj.data.copy()
        draft.objects.link(adjusted)
        changed = equalize(adjusted, groups)
        if changed:
            pairs.append((obj, adjusted, groups, changed))
        else:
            bpy.data.objects.remove(adjusted, do_unlink=True)
    if not pairs:
        raise ValueError("no discrepant coincident upper-limb vertices")
    indices = [0, scene.frame_end // 2, scene.frame_end] if key_phases else list(range(scene.frame_end + 1))
    results = {}
    for i in indices:
        record = frames[i]
        scene.frame_set(i)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        check_arm_bone_pose(record, graph)
        bones = bone_surfaces(scene.collection.children["bones"].objects, graph)
        rows = {}
        for old, new, groups, count in pairs:
            a, faces = surface(old, graph)
            b, revised_faces = surface(new, graph)
            if not np.array_equal(faces, revised_faces):
                raise ValueError(f"seam adjustment changed topology: {old.name}")
            row = {
                "seam_m_before": seam_width(a, groups),
                "seam_m_after": seam_width(b, groups),
                "max_vertex_change_m": float(np.linalg.norm(a - b, axis=1).max()),
                "crossings_before": sum(intersections(a, faces, bones).values()),
                "crossings_after": sum(intersections(b, faces, bones).values()),
                "coincident_groups_changed": count,
            }
            actuator = paths.get(old.name)
            if actuator:
                segments = sorted((p for p in record["paths"] if p["actuator"] == actuator),
                                  key=lambda p: p["segment"])
                endpoint = [Vector(segments[0]["start_m"]), Vector(segments[-1]["end_m"])]
                row["endpoints_before_m"] = [tree(a, faces).find_nearest(p)[3] for p in endpoint]
                row["endpoints_after_m"] = [tree(b, faces).find_nearest(p)[3] for p in endpoint]
            rows[old["source_label"]] = row
        results[i] = {"source_index": record["source_index"], "surfaces": rows}
    (output / "seam-study.json").write_text(json.dumps({
        "status": "EXPERIMENTAL_SKIN_WEIGHT_REPAIR",
        "sample_count": len(indices),
        "frames": results,
    }, indent=2))
    return pairs, results


def install(scene, output, expected):
    pairs, measured = trial(scene, output, expected, False)
    if not measured or len(measured) != scene.frame_end + 1:
        raise ValueError("seam fit must cover the saved timeline")
    atlas = scene.collection.children[ATLAS]
    archive = bpy.data.collections.new("Upper-limb seams · source weights")
    atlas.children.link(archive)
    active = set()
    for old, new, _, _ in pairs:
        label = old["source_label"]
        rows = [frame["surfaces"][label] for frame in measured.values()]
        if max(row["seam_m_before"] for row in rows) < .0005:
            bpy.data.objects.remove(new, do_unlink=True)
            continue
        if max(row["seam_m_after"] for row in rows) > 1e-6:
            raise ValueError(f"position-identical seam still opens: {label}")
        if any(any(y - x > .001 for x, y in zip(row.get("endpoints_before_m", []),
                                                row.get("endpoints_after_m", []), strict=True)) for row in rows):
            bpy.data.objects.remove(new, do_unlink=True)
            continue
        for group in list(old.users_collection):
            group.objects.unlink(old)
        archive.objects.link(old)
        new["correction"] = "Coincident rest vertices share a normalized mean skin weight"
        active.add(label)
    if not active:
        raise ValueError("no verified seam repairs")
    archive.hide_render = True
    bpy.context.view_layer.layer_collection.children[ATLAS].children[archive.name].hide_viewport = True
    bpy.data.texts.new("Upper-limb seam fit · evidence").write(
        "Candidate visual skin-weight repair. Exact coincident positions were compared within each "
        "source mesh. Assigned weights are averaged within each such group. Separate muscle "
        "volumes, bone animation and topology are retained. Attachment anatomy remains under review."
    )
    scene.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "arms-continuous.blend"), compress=True)
    rows = [row for frame in measured.values() for label, row in frame["surfaces"].items() if label in active]
    (output / "seam-fit.json").write_text(json.dumps({
        "status": "ILLUSTRATIVE_SKIN_WEIGHT_REPAIR",
        "active_surfaces": sorted(active),
        "repaired_surface_count": len(active),
        "sample_count": len(measured),
        "worst_open_seam_before_m": max(row["seam_m_before"] for row in rows),
        "worst_open_seam_after_m": max(row["seam_m_after"] for row in rows),
        "maximum_vertex_change_m": max(row["max_vertex_change_m"] for row in rows),
        "bone_triangle_crossings_before": sum(row["crossings_before"] for row in rows),
        "bone_triangle_crossings_after": sum(row["crossings_after"] for row in rows),
    }, indent=2))


if __name__ == "__main__":
    folder, mapping, *mode = sys.argv[sys.argv.index("--") + 1:]
    expected = json.loads(Path(mapping).read_text())
    if mode == ["preview"]:
        trial(bpy.context.scene, Path(folder), expected, True)
    elif not mode:
        install(bpy.context.scene, Path(folder), expected)
    else:
        raise ValueError("expected no mode or 'preview'")
