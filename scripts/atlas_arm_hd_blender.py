"""Reuse the pinned, full-resolution source arm meshes on the saved-state rig."""

import json
from pathlib import Path
import sys

import bpy
import numpy as np

from atlas_arm_review_blender import audit, path_muscles
from atlas_arm_seams_blender import duplicate_positions, equalize, upper_limb_objects
from atlas_arm_surface_blender import topology
from atlas_collision_blender import ATLAS
from atlas_reference import ASSET_BASE_URL, ASSETS, LICENSE


def geometry(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangles = np.empty((len(mesh.loop_triangles), 3), np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    first, weld, *_ = topology(obj, triangles)
    edges = weld[triangles[:, [0, 1, 1, 2, 2, 0]]].reshape(-1, 2)
    _, incidence = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    return {"vertices": len(first), "triangles": len(triangles),
            "open_edges": int(sum(incidence == 1)), "nonmanifold_edges": int(sum(incidence > 2))}


def muscle_bones(obj):
    return {obj.vertex_groups[group.group].name for vertex in obj.data.vertices
            for group in vertex.groups if group.weight > 0}


def run(scene, expected, source, output):
    previous_paths = audit(scene, expected)
    originals = {o["source_label"]: o for o in [*upper_limb_objects(scene), *path_muscles(scene).values()]}
    rig = next(o.find_armature() for o in originals.values() if o.find_armature() is not None)
    old_bones = {o["source_label"]: muscle_bones(o) for o in scene.objects
                 if o.type == "MESH" and o.get("source_label") in originals and o.find_armature() == rig}
    names = {label[:63] for label in originals}
    with bpy.data.libraries.load(str(source), link=False) as (available, imported):
        imported.objects = sorted(names.intersection(available.objects))
        imported.texts = ["Reference atlas · provenance"]
    receipt = json.loads(imported.texts[0].as_string())
    name, _, digest = ASSETS["hd"]
    if (receipt["sha256"], receipt["source_url"], receipt["license"]) != (digest, ASSET_BASE_URL + name, LICENSE):
        raise ValueError("not the pinned full-resolution atlas reference")
    high_res = {o["source_label"]: o for o in imported.objects if o.type == "MESH" and "source_label" in o}
    atlas = scene.collection.children[ATLAS]
    layer = bpy.data.collections.new("Upper limb · full-resolution source")
    archive = bpy.data.collections.new("Upper limb · light source archive")
    atlas.children.link(layer)
    atlas.children.link(archive)
    rows = {}
    for label, old in originals.items():
        new = high_res[label]
        source_rig = new.find_armature()
        weighted = muscle_bones(new)
        if not weighted or not weighted <= old_bones[label]:
            raise ValueError(f"unverified full-resolution bone influences: {label}")
        if not np.allclose(np.asarray(source_rig.matrix_world), np.asarray(rig.matrix_world), atol=1e-6, rtol=0):
            raise ValueError("source and replay rig use different world axes")
        errors = {name: (rig.data.bones[name].head_local - source_rig.data.bones[name].head_local).length
                  for name in weighted}
        if max(errors.values()) > 1e-6:
            raise ValueError(f"source and replay bind locations differ: {label}")
        before, after = geometry(old), geometry(new)
        coincident = duplicate_positions(new)
        rows[label] = {"light": before, "full_resolution": after,
                       "equalized_weight_groups": equalize(new, coincident),
                       "max_bind_location_difference_m": max(errors.values())}
        layer.objects.link(new)
        new.parent = rig
        for modifier in new.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = rig
        new.hide_render = False
        new.hide_set(False)
        new["correction"] = "Full-resolution MyoSuite surface using existing world-space bone deformations"
        for collection in list(old.users_collection):
            collection.objects.unlink(old)
        archive.objects.link(old)
    archive.hide_render = True
    bpy.context.view_layer.layer_collection.children[ATLAS].children[archive.name].hide_viewport = True
    next_paths = audit(scene, expected)
    scene.frame_set(0)
    bpy.data.texts.new("Full-resolution arm source · evidence").write(json.dumps({
        "source_url": receipt["source_url"], "sha256": digest, "license": LICENSE,
        "attribution": receipt["attribution"], "method": "Named mesh transfer using the existing animated armature.",
        "limits": "Surface topology and saved-state playback checks only. Tissue geometry and contact need anatomical validation.",
    }, indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "arm-hd.blend"), compress=True)
    (output / "arm-hd.json").write_text(json.dumps({
        "source": receipt, "topology": rows, "paths_before": previous_paths, "paths_after": next_paths,
    }, indent=2))


if __name__ == "__main__":
    out, mapping, hd_source = map(Path, sys.argv[sys.argv.index("--") + 1:])
    run(bpy.context.scene, json.loads(mapping.read_text()), hd_source, out)
