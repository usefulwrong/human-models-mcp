"""Transfer the source rectus meshes onto saved pubic and costal model sites."""

from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


SIDES = ("r", "l")
SOURCE_OBJECT = "Rectus abdominis muscle"


def source_meshes():
    """Bake the pinned source scene's hierarchy and retain tendon assignments."""
    bpy.context.view_layer.update()
    for side in SIDES:
        original = bpy.data.objects[f"{SOURCE_OBJECT}.{side}"]
        if [material.name for material in original.data.materials] != ["Flexion", "Tendon"]:
            raise ValueError("unexpected material slots on the pinned Z-Anatomy rectus")
        assignments = np.empty(len(original.data.polygons), dtype=np.int32)
        original.data.polygons.foreach_get("material_index", assignments)
        if len(assignments) != 20604 or np.count_nonzero(assignments == 1) != 6611:
            raise ValueError("pinned rectus material assignment differs")
        mesh = original.data.copy()
        mesh.transform(original.matrix_world)
        mesh.materials.clear()
        mask = mesh.attributes.new("atlas_source_tendon", "BOOLEAN", "FACE")
        mask.data.foreach_set("value", assignments == 1)
        yield side, original, mesh, assignments


def extract_world_meshes(destination):
    meshes = set()
    for side, original, mesh, _ in source_meshes():
        obj = bpy.data.objects.new(f"atlas-source-rectus-{side}", mesh)
        obj["source_object"] = original.name
        meshes.add(obj)
    bpy.data.libraries.write(str(destination), meshes, compress=True)


def extract_portable(destination):
    arrays = {}
    for side, _, mesh, assignments in source_meshes():
        vertices = np.empty(len(mesh.vertices) * 3, dtype="<f4")
        faces = np.empty(len(mesh.loops), dtype="<i4")
        mesh.vertices.foreach_get("co", vertices)
        mesh.loops.foreach_get("vertex_index", faces)
        if len(faces) != len(mesh.polygons) * 3 or any(len(p.vertices) != 3 for p in mesh.polygons):
            raise ValueError("pinned rectus polygons must be triangles")
        arrays.update({f"{side}_vertices": vertices.reshape(-1, 3), f"{side}_faces": faces.reshape(-1, 3),
                       f"{side}_tendon": assignments.astype("u1")})
    with destination.open("xb") as stream:
        np.savez_compressed(stream, **arrays)


def segment_frame(lower, upper, anatomical_left):
    axis = upper - lower
    length = axis.length
    if not .2 < length < .65:
        raise ValueError("rectus landmark distance outside metre-scale bounds")
    superior = axis / length
    left = anatomical_left - superior * anatomical_left.dot(superior)
    if left.length < .02:
        raise ValueError("rectus lateral and longitudinal landmarks are degenerate")
    left.normalize()
    posterior = superior.cross(left)
    return Matrix((left, posterior, superior)).transposed(), length


def transfer_rectus(scene, source, frames, material):
    names = [f"atlas-source-rectus-{side}" for side in SIDES]
    with bpy.data.libraries.load(str(source), link=False) as (available, selected):
        if not set(names).issubset(available.objects):
            raise ValueError("pinned Z-Anatomy rectus objects absent")
        selected.objects = names
    collection = bpy.data.collections.new("Rectus abdominis · Z-Anatomy")
    scene.collection.children.link(collection)
    result = []
    for side, source_obj in zip(SIDES, selected.objects, strict=True):
        if source_obj.type != "MESH" or len(source_obj.data.vertices) != 10304:
            raise ValueError("unexpected source rectus mesh")
        mesh = source_obj.data.copy()
        coords = np.array([list(v.co) for v in mesh.vertices])
        lower, upper = coords[:, 2].min(), coords[:, 2].max()
        if not (.84 < lower < .86 and 1.24 < upper < 1.27):
            raise ValueError("Z-Anatomy source transform differs from pinned world coordinates")
        lower_ref = Vector(coords[coords[:, 2] < lower + .012].mean(axis=0))
        upper_ref = Vector(coords[coords[:, 2] > upper - .012].mean(axis=0))
        bind_axis, bind_length = segment_frame(lower_ref, upper_ref, Vector((1, 0, 0)))
        mesh.transform(Matrix.Translation(-lower_ref))
        mesh.materials.clear()
        mesh.materials.append(material)
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        obj = bpy.data.objects.new(SOURCE_OBJECT + " · " + side.upper(), mesh)
        obj["source"] = "Z-Anatomy · CC BY-SA 4.0"
        obj["source_object"] = source_obj["source_object"]
        obj["role"] = "illustrative landmark registration"
        collection.objects.link(obj)
        obj.rotation_mode = "QUATERNION"
        mesh.transform(bind_axis.transposed().to_4x4())
        checks = []
        for index, frame in enumerate(frames):
            sites = frame["rectus_sites_m"]
            lo, *_, hi = map(Vector, sites[side])
            left = Vector(sites["l"][-1]) - Vector(sites["r"][-1])
            basis, length = segment_frame(lo, hi, left)
            ratio = length / bind_length
            if not .73 <= ratio <= 1.35:
                raise ValueError(f"rectus transfer beyond axial scale bound: {ratio}")
            obj.location = lo
            obj.rotation_quaternion = basis.to_quaternion()
            obj.scale = (1, 1, ratio)
            for key in ("location", "rotation_quaternion", "scale"):
                obj.keyframe_insert(data_path=key, frame=index)
            checks.append({"source_index": frame["index"], "axial_scale": ratio})
        local = np.array([list(v.co) for v in mesh.vertices])
        for i, (frame, check) in enumerate(zip(frames, checks, strict=True)):
            scene.frame_set(i)
            bpy.context.view_layer.update()
            world = np.asarray(obj.matrix_world)
            sites = frame["rectus_sites_m"]
            right, left = (np.asarray(sites[key]) for key in ("r", "l"))
            middle = (left + right) / 2
            lateral = left[-1] - right[-1]
            lateral /= np.linalg.norm(lateral)
            centreline = obj.matrix_world @ Vector((0, 0, bind_length))
            error = max((obj.matrix_world.translation - Vector(sites[side][0])).length,
                        (centreline - Vector(sites[side][-1])).length)
            vertices = local @ world[:3, :3].T + world[:3, 3]
            signed = (vertices - middle[0]) @ lateral * (1 if side == "l" else -1)
            if error > 2e-6 or not np.isfinite(vertices).all() or np.median(signed) <= 0:
                raise ValueError("rectus centreline, scale or laterality mismatch")
            check.update({"anchor_error_m": error,
                          "fraction_of_vertices_across_midline": float(np.mean(signed < 0)),
                          "minimum_surface_z_m": float(vertices[:, 2].min())})
        result.append({"source_object": source_obj["source_object"], "vertices": len(mesh.vertices),
                       "target_sites": [f"rect_abd_{side}-P1", f"rect_abd_{side}-P4"],
                       "source_endpoint_method": "centroids of 12 mm superior and inferior vertex caps",
                       "checks": checks})
    return collection, result


if __name__ == "__main__":
    destination = Path(sys.argv[sys.argv.index("--") + 1])
    if destination.suffix == ".npz":
        extract_portable(destination)
    else:
        extract_world_meshes(destination)
