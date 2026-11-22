"""Default procedural display materials for volumetric muscle meshes in Blender."""

import bpy
import numpy as np


COORDINATES = "atlas_material_coordinates_m"
SOURCE_TENDON = "atlas_source_tendon"
FIBROUS_MUSCLE = "Atlas muscle · procedural fibres"
SOURCE_MARKED_TENDON = "Atlas tendon · source-marked faces"


def texture_coordinates(mesh, anatomical_axis=None):
    """Store fixed local coordinates so the texture follows the animated mesh."""
    points = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", points.ravel())
    if not len(points) or not np.isfinite(points).all():
        raise ValueError(f"cannot map muscle material coordinates on {mesh.name}")
    points -= points.mean(axis=0)
    if anatomical_axis == "local_z":
        coordinates = points
    else:
        _, basis = np.linalg.eigh(points.T @ points)
        for column in basis.T:
            column *= 1 if column[np.argmax(np.abs(column))] >= 0 else -1
        coordinates = points @ basis
    attribute = mesh.attributes.get(COORDINATES)
    if attribute is None:
        attribute = mesh.attributes.new(COORDINATES, "FLOAT_VECTOR", "POINT")
    attribute.data.foreach_set("vector", np.ascontiguousarray(coordinates).ravel())


def material(tendon=False):
    name = SOURCE_MARKED_TENDON if tendon else FIBROUS_MUSCLE
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    nodes, links = result.node_tree.nodes, result.node_tree.links
    shader = nodes["Principled BSDF"]
    texture = nodes.new("ShaderNodeAttribute")
    texture.attribute_name = COORDINATES
    texture.label = "Fixed per-vertex material coordinates"
    stretch = nodes.new("ShaderNodeVectorMath")
    stretch.operation = "MULTIPLY"
    stretch.inputs[1].default_value = (250, 250, 12) if tendon else (245, 245, 10)
    links.new(texture.outputs["Vector"], stretch.inputs[0])
    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 1
    grain.inputs["Detail"].default_value = 2
    grain.inputs["Roughness"].default_value = .52
    links.new(stretch.outputs["Vector"], grain.inputs["Vector"])
    shades = nodes.new("ShaderNodeValToRGB")
    dark, light = ((.25, .14, .10, 1), (.61, .43, .31, 1)) if tendon else (
        (.095, .014, .010, 1), (.44, .092, .056, 1)
    )
    low, high = shades.color_ramp.elements
    low.position, low.color = .22, dark
    high.position, high.color = .78, light
    links.new(grain.outputs["Fac"], shades.inputs["Fac"])
    links.new(shades.outputs["Color"], shader.inputs["Base Color"])
    relief = nodes.new("ShaderNodeBump")
    relief.inputs["Strength"].default_value = .18 if tendon else .27
    relief.inputs["Distance"].default_value = .00065 if tendon else .001
    links.new(grain.outputs["Fac"], relief.inputs["Height"])
    links.new(relief.outputs["Normal"], shader.inputs["Normal"])
    shader.inputs["Roughness"].default_value = .52 if tendon else .48
    result.diffuse_color = light
    return result


def set_source_tendon_mask(mesh, mask):
    if len(mask) != len(mesh.polygons) or not np.isin(mask, (0, 1)).all():
        raise ValueError("source tendon face assignment differs from mesh topology")
    target = mesh.attributes.get(SOURCE_TENDON)
    if target is None:
        target = mesh.attributes.new(SOURCE_TENDON, "BOOLEAN", "FACE")
    target.data.foreach_set("value", np.asarray(mask, dtype=np.bool_))


def apply(mesh, anatomical_axis=None):
    """Apply the default muscle appearance and retain any source-marked tendon faces."""
    texture_coordinates(mesh, anatomical_axis)
    mesh.materials.clear()
    mesh.materials.append(material())
    tendon = mesh.attributes.get(SOURCE_TENDON)
    count = 0
    if tendon is not None:
        mask = np.empty(len(mesh.polygons), dtype=np.bool_)
        tendon.data.foreach_get("value", mask)
        mesh.materials.append(material(tendon=True))
        mesh.polygons.foreach_set("material_index", mask.astype(np.int32))
        count = int(np.count_nonzero(mask))
    return count
