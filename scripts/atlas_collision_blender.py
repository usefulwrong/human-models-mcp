"""Inspect actual animated bone–surface intersections in the research atlas."""

import json
from pathlib import Path
import sys

import bpy
from mathutils.bvhtree import BVHTree
import numpy as np


ATLAS = "Candidate mesh transfer · engineering probe"
RECTUS = "Rectus abdominis · Z-Anatomy"


def surface(obj, graph):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.data
    mesh.calc_loop_triangles()
    points = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.vertices.foreach_get("co", points.ravel())
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    matrix = np.asarray(evaluated.matrix_world)
    points = points @ matrix[:3, :3].T + matrix[:3, 3]
    if not np.isfinite(points).all() or len(triangles) == 0:
        raise ValueError(f"unusable surface: {obj.name}")
    return points, triangles


def tree(points, triangles):
    return BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True)


def check_detector():
    triangle = np.array([[0, 1, 2]])
    flat = tree(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]), triangle)
    intersecting = tree(np.array([[.25, .2, -.5], [.25, .2, .5], [.25, .8, 0.]]), triangle)
    disjoint = tree(np.array([[.65, .65, -.5], [.65, .65, .5], [.65, .9, 0.]]), triangle)
    if not flat.overlap(intersecting) or flat.overlap(disjoint):
        raise ValueError("triangle intersection detector failed positive or negative control")


def bone_surfaces(objects, graph):
    bones = []
    for obj in objects:
        if obj.type == "MESH":
            pose, faces = surface(obj, graph)
            bones.append((obj.name, pose.min(axis=0), pose.max(axis=0), tree(pose, faces)))
    return bones


def intersections(pose, faces, bones):
    lower, upper = pose.min(axis=0), pose.max(axis=0)
    atlas = tree(pose, faces)
    collisions = {}
    for name, bone_lower, bone_upper, bone in bones:
        if (upper < bone_lower).any() or (bone_upper < lower).any():
            continue
        crossings = atlas.overlap(bone)
        if crossings:
            collisions[name] = len(crossings)
    return collisions


def rendered_meshes(collection):
    if collection.hide_render:
        return
    yield from (obj for obj in collection.objects if obj.type == "MESH" and not obj.hide_render)
    for child in collection.children:
        yield from rendered_meshes(child)


def frame_collisions(scene, frame, muscles=None):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    groups = scene.collection.children
    if muscles is None:
        muscles = [obj for layer in (ATLAS, RECTUS) for obj in rendered_meshes(groups[layer])]
    bones = bone_surfaces(groups["bones"].objects, graph)
    overlaps = {}
    for obj in muscles:
        pose, faces = surface(obj, graph)
        collisions = intersections(pose, faces, bones)
        if collisions:
            overlaps[obj.get("source_label", obj.name)] = collisions
    return overlaps


def main(path):
    check_detector()
    scene = bpy.context.scene
    sampled = [0, scene.frame_end // 2, scene.frame_end]
    frames = {frame: frame_collisions(scene, frame) for frame in sampled}
    data = {
        "method": "World-space triangle intersection pairs using Blender BVH",
        "limitations": "Includes contacts near attachments. No classification of biological attachment or intersection volume.",
        "frames": frames,
    }
    path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[sys.argv.index("--") + 1]))
