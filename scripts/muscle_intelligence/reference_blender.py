"""Render the same evidence points on a freshly reopened MotionScene."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_muscles import BASIS, FRAMES, digest, dump, phase_camera, setup_render, still  # noqa: E402


def markers(scene, name, count, radius, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    surface = mat.node_tree.nodes.get("Principled BSDF")
    surface.inputs["Base Color"].default_value = (*color, 1)
    surface.inputs["Emission Color"].default_value = (*color, 1)
    surface.inputs["Emission Strength"].default_value = 0.7
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius)
    first = bpy.context.object
    first.name = name
    first.data.materials.append(mat)
    result = [first]
    for _ in range(count - 1):
        obj = first.copy()
        scene.collection.objects.link(obj)
        result.append(obj)
    return result


def render(receipt, expected, output):
    if digest(receipt) != expected:
        raise ValueError("registration evidence SHA-256 differs")
    doc = json.loads(receipt.read_bytes())
    scene = bpy.context.scene
    if any(doc[k] != scene[k] for k in ("run_id", "motion_sha256")) or (
            doc["mapping_revision_sha256"] != scene["muscle_mapping_sha256"]):
        raise ValueError("evidence and reopened Blender scene differ")
    pilot = doc["pilots"]["239"]
    obj = next(x for x in scene.objects if x.get("motion_node") == pilot["node"])
    clavicle = scene.objects["clavicle"]
    bone = doc["bones"]["clavicle"]
    fit, = bone["alternatives"]
    route = doc["routes"][pilot["native_route"]]["samples"]
    atlas = np.asarray(fit["atlas_preview_geom_m"])
    fit_points = np.asarray([m["target_geom_m"] for m in fit["markers"] if m["role"] == "FIT"])
    held = np.asarray([m["target_geom_m"] for m in fit["markers"] if m["role"] == "HELD_OUT"])
    sets = [
        (markers(scene, "BodyParts3D clavicle sample (archived ICP)", len(atlas), .0016, (.65, .24, .95)), atlas),
        (markers(scene, "Fit proxy", len(fit_points), .004, (1, .65, .12)), fit_points),
        (markers(scene, "Held-out proxy", len(held), .0045, (1, .20, .09)), held),
    ]
    icp = np.asarray(fit["archived_icp"]["source_mm_to_native_geom_m"])
    for item in fit.get("annotations", []):
        source = np.asarray(item["source_mm"]) @ icp[:3, :3].T + icp[:3, 3]
        sets.append((markers(scene, "Operator source · " + item["name"], 1, .004, (.8, .35, 1)), [source]))
        sets.append((markers(scene, "Operator target · " + item["name"], 1, .004, (1, 1, 1)),
                     [item["target_geom_m"]]))
    sites = markers(scene, "Saved model site", len(route[0]["model_sites_world_m"]), .004, (.05, .75, 1))
    # Model site dots and the absolute path stay in the recorded MuJoCo world.
    mat = sites[0].data.materials[0]
    curve = bpy.data.curves.new("Saved MuJoCo wrap polyline", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = .0012
    curve.materials.append(mat)
    line = bpy.data.objects.new(curve.name, curve)
    scene.collection.objects.link(line)
    scene.camera.data.type = "ORTHO"
    phase_camera(scene, scene.camera, [obj, clavicle], FRAMES, .42)
    setup_render(scene)
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1050
    camera = scene.camera
    basis = np.eye(4)
    basis[:3, :3] = BASIS
    stats = []
    for index in FRAMES:
        scene.frame_set(index)
        snap = doc["frames"][index]
        data = route[index]
        if (data["state_index"], data["time_s"]) != (index, snap["frame_time"]) or not np.isclose(
            index / scene.render.fps, snap["frame_time"], atol=1e-12, rtol=0
        ):
            raise ValueError("Blender and saved frame clocks differ")
        transform = np.asarray(clavicle.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world)
        for objects, points in sets:
            for marker, point in zip(objects, np.asarray(points) @ transform[:3, :3].T + transform[:3, 3], strict=True):
                marker.location = Vector(point)
        for marker, point in zip(sites, data["model_sites_world_m"], strict=True):
            marker.location = Vector(point)
        curve.splines.clear()
        points = data["wrap_polyline_world_m"]
        path = curve.splines.new("POLY")
        path.points.add(len(points) - 1)
        for vertex, point in zip(path.points, points, strict=True):
            vertex.co = (*point, 1)
        stats.append({"frame": snap, "native_bone_node": bone["native"]["node"],
                      "bone_matrix_glb_column_major": (basis @ transform @ basis.T).T.ravel().tolist(),
                      "route_sites_world_m": [list(marker.location) for marker in sites],
                      "route_polyline_world_m": [list(point.co[:3]) for point in path.points],
                      "markers_world_m": [[list(marker.location) for marker in objects] for objects, _ in sets],
                      "camera": {"location_m": list(camera.location), "rotation_rad": list(camera.rotation_euler),
                                 "ortho_width_m": camera.data.ortho_scale}})
        still(scene, output / f"reference-pectoral-{index:03}.png")
    dump(output / "reference-blender.json", {"anatomical_registration": doc["anatomical_registration"],
         "run_id": doc["run_id"], "motion_sha256": doc["motion_sha256"],
         "engine": scene.render.engine, "cycles_device": scene.cycles.device,
         "bone_pair": {"source_fj_id": fit["source_fj_id"], "target_geom": fit["target_geom"],
                       "source_sha256": fit["source_sha256"], "target_sha256": fit["target_mesh_sha256"]},
         "legend": ["Atlas preview / purple", "Geometric fit proxies / yellow", "Geometric held-out proxies / orange",
                    "Operator pairs / purple and white (when installed)", "Saved route and sites / cyan"],
         "evidence_sha256": expected, "camera_orthographic_width_m": camera.data.ortho_scale, "states": stats})


if __name__ == "__main__":
    evidence, sha, directory = sys.argv[sys.argv.index("--") + 1:]
    render(Path(evidence), sha, Path(directory))
