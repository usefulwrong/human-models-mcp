"""Compare first-state model-anchor transport with the pinned LBS in Blender."""

import json
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_muscles import (BASIS, Clip, FRAMES, bone_surfaces, check_detector, digest, dump,  # noqa: E402
                             intersections, is_closed, phase_camera, quality, setup_render, still,
                             surface, topology)
from glb import normals  # noqa: E402

RADIUS_M = 0.030
CAP_M = 0.006
METHODS = ("lbs", "anchor")
REGIONS = {
    "pectoral": [228, 229, 237, 239, 495, 496],
    "deep-shoulder": [351, 460],
    "lower-leg": [348, 457],
    "negative-oblique": [290, 402],
}


def near(bvh, points):
    return np.array([float(bvh.find_nearest(Vector(p))[3]) for p in points])


def region_bones(region, side):
    if region == "pectoral":
        return ("Sternum", "clavicle", "humerus") if side == "right" else ("Sternum", "clavicle_mirror", "humerus_mirror")
    if region == "deep-shoulder":
        return ("scapula", "humerus") if side == "right" else ("scapula_mirror", "humerus_mirror")
    if region == "lower-leg":
        return ("r_tibia", "r_fibula", "r_foot") if side == "right" else ("l_tibia", "l_fibula", "l_foot")
    return ("Rib5R", "Rib6R", "r_pelvis") if side == "right" else ("Rib5L", "Rib6L", "l_pelvis")


def model_anchors(points, samples):
    initial = samples[0]
    endpoints = np.asarray(initial["model_sites_world_m"])[[0, -1]]
    rotation = np.asarray(initial["endpoint_rotation_world"])
    delta = points[:, None] - endpoints
    dist = np.linalg.norm(delta, axis=2)
    owner = dist.argmin(axis=1)
    weight = np.clip(1 - dist[np.arange(len(points)), owner] / RADIUS_M, 0, 1)
    weight = weight**2 * (3 - 2 * weight)
    local = np.einsum("nji,nj->ni", rotation[owner], points - endpoints[owner])
    return owner, weight, local


def candidate(points, sample, anchors):
    owner, weight, local = anchors
    endpoints = np.asarray(sample["model_sites_world_m"])[[0, -1]]
    rotation = np.asarray(sample["endpoint_rotation_world"])[owner]
    target = np.einsum("nij,nj->ni", rotation, local) + endpoints[owner]
    step = (target - points) * weight[:, None]
    step *= (CAP_M / np.maximum(CAP_M, np.linalg.norm(step, axis=1)))[:, None]
    return points + step


def max_norm(v):
    return float(np.linalg.norm(v, axis=1).max())


def run(native_path, output):
    source = json.loads(native_path.read_bytes())
    scene = bpy.context.scene
    assert (source["run_id"] == scene["run_id"] and source["motion_sha256"] == scene["motion_sha256"]
            and source["mapping_revision_sha256"] == scene["muscle_mapping_sha256"])
    assert tuple(source["anchors"]) == FRAMES and len(source["clock_s"]) == 111
    check_detector()
    original = {int(obj["motion_node"]): obj for obj in scene.objects if "motion_node" in obj}
    skeleton = scene.collection.children["SKELETON"]
    gltf_world = {}
    scene.frame_set(0)
    graph = bpy.context.evaluated_depsgraph_get()
    rows, snapshots, lookup = {}, {}, {}
    for region, nodes in REGIONS.items():
        for node in nodes:
            obj = original[node]
            item = source["pilot_surfaces"][str(node)]
            name = item["route_control"]
            assert obj["display_sha256"] == item["geometry_sha256"]
            measured = name is not None
            linked = measured and not name.startswith("PECM3")
            points, faces = surface(obj, graph)
            topo = topology(obj, faces)
            closed = is_closed(faces, topo[1])
            route = source["routes"][name]["samples"] if measured else None
            anchors = model_anchors(points, route) if linked else None
            if anchors:
                np.testing.assert_allclose(candidate(points, route[0], anchors), points, atol=1e-12)
            rows[node] = {"region": region, "name": item["name"], "side": item["side"], "source": item["dataset"],
                          "source_geometry_sha256": item["geometry_sha256"], "model_route": name,
                          "mapping": obj["display_mapping_status"], "bone_targets": region_bones(region, item["side"]),
                          "candidate": "TESTED" if linked else "NOT_RUN_NO_ACCEPTED_PART",
                          "weighted_vertices": int(np.count_nonzero(anchors[1])) if anchors else 0,
                          "vertices": len(points), "triangles": len(faces),
                          "closed_welded_and_oriented": closed, "independent_footprints": "NOT_VERIFIED",
                          "max_edit_m": 0, "frames": {}, "continuity": {
                              method: {"state_step_m": [], "step_difference_m": []} for method in METHODS
                              if method == "lbs" or linked}}
            snapshots[node] = {k: [] for k in rows[node]["continuity"]}
            lookup[node] = obj, faces, topo, closed, route, anchors
    previous = {}
    for i in range(111):
        scene.frame_set(i)
        graph = bpy.context.evaluated_depsgraph_get()
        bones = bone_surfaces(skeleton.objects, graph) if i in FRAMES else None
        if bones is not None:
            bone_lookup = {bone[0]: bone[-1] for bone in bones}
            gltf_world[i] = {obj.name: surface(obj, graph) for obj in skeleton.objects if obj.type == "MESH"
                             and any(obj.name in row["bone_targets"] for row in rows.values())}
        for node, (obj, faces, topo, closed, route, anchors) in lookup.items():
            points, tris = surface(obj, graph)
            assert np.array_equal(tris, faces)
            row = rows[node]
            sample = route[i] if route else None
            endpoints = np.asarray(sample["model_sites_world_m"])[[0, -1]] if sample else None
            variants = {"lbs": points}
            if anchors:
                variants["anchor"] = candidate(points, sample, anchors)
                row["max_edit_m"] = max(row["max_edit_m"], max_norm(variants["anchor"] - points))
            for method, pts in variants.items():
                key = node, method
                old, old_step = previous.get(key, (None, None))
                step = pts - old if old is not None else None
                if step is not None:
                    row["continuity"][method]["state_step_m"].append(max_norm(step))
                if old_step is not None:
                    row["continuity"][method]["step_difference_m"].append(max_norm(step - old_step))
                previous[key] = pts, step
                if bones is None:
                    continue
                report = quality(pts, points, faces, topo[1], endpoints, bones, closed)
                report["bone_intersections_by_name"] = intersections(pts, faces, bones)
                assert sum(report["bone_intersections_by_name"].values()) == report["bone_intersection_pairs"]
                report["surface_bone_nearest_vertex_m"] = {}
                for bone in row["bone_targets"]:
                    bvh = bone_lookup[bone]
                    distances = near(bvh, pts)
                    report["surface_bone_nearest_vertex_m"][bone] = {
                        "min": float(distances.min()), "median": float(np.median(distances)),
                        "p95": float(np.quantile(distances, .95)),
                        "model_endpoint_distances": near(bvh, endpoints).tolist() if endpoints is not None else None}
                a, b = topo[2:4]
                lengths = np.linalg.norm(pts[topo[0][a]] - pts[topo[0][b]], axis=1)
                baseline = np.linalg.norm(points[topo[0][a]] - points[topo[0][b]], axis=1)
                use = baseline > 1e-10
                report["collapsed_nonzero_baseline_edges"] = int(np.count_nonzero(use & (lengths <= 1e-10)))
                report["edge_length_ratio_to_lbs_min_max"] = [float((lengths[use]/baseline[use]).min()),
                                                            float((lengths[use]/baseline[use]).max())]
                report["vertices_below_floor"] = int(np.count_nonzero(pts[:, 2] < 0))
                row["frames"].setdefault(i, {})[method] = report
                snapshots[node][method].append(pts)
    assert all(len(r["frames"]) == 5 for r in rows.values())
    decisions = {}
    for node, row in rows.items():
        if row["candidate"] != "TESTED":
            continue
        keys = ("bone_intersection_pairs", "self_intersection_pairs", "floor_crossing_triangles",
                "against_baseline_normal_faces", "collapsed_nonzero_baseline_edges")
        worsened = [(i, k) for i, pair in row["frames"].items() for k in keys if pair["anchor"][k] > pair["lbs"][k]]
        decisions[node] = {"worsened_frame_metrics": worsened, "status": "REJECT" if worsened else "INCONCLUSIVE"}
    outcome = "REJECT" if any(r["status"] == "REJECT" for r in decisions.values()) else "INCONCLUSIVE"
    manifest = {"run_id": source["run_id"], "motion_sha256": source["motion_sha256"],
                "mapping_revision_sha256": source["mapping_revision_sha256"], "crosswalk_revision": 3,
                "native_qa_sha256": digest(native_path), "frames": FRAMES, "states": 111, "units": "m, m², m³",
                "method": {"name": "First-pose endpoint-neighborhood rigid transport blended into LBS",
                           "radius_m": RADIUS_M, "max_vertex_delta_m": CAP_M, "reference_state": 0,
                           "formula": "Nearest endpoint at state 0. Store unshifted vertex in that endpoint body's local "
                                      "frame. Transport by saved rotation and site center, blend with original LBS "
                                      "by fixed smoothstep distance weight and cap displacement.",
                           "restore": "Use immutable MotionScene GLB with authored LBS.",
                           "limitations": "Point sites are model anchors. Bone BVH counts intersecting triangle pairs, "
                                          "without inside-depth claims. Volume applies only to consistently oriented "
                                          "closed meshes. Normal reversals are relative to matching LBS faces."},
                "decision": outcome, "decisions": decisions, "pieces": rows}
    dump(output / "DEFORMATION_BENCHMARK.json", manifest)
    print("Geometry finished", outcome, len(rows), "surfaces", flush=True)
    setup_render(scene)
    scene.cycles.samples = 4
    scene.render.resolution_x, scene.render.resolution_y = 640, 420
    scene.camera = bpy.data.objects["Research torso"]
    scene.camera.data.type = "ORTHO"
    scene.camera.data.sensor_fit = "HORIZONTAL"
    bpy.data.collections["MUSCLES"].hide_render = True
    bpy.data.collections["BODY"].hide_render = True
    target = bpy.data.collections.new("Registration mesh comparison")
    scene.collection.children.link(target)
    comparisons = {}
    for region, nodes in REGIONS.items():
        phase_camera(scene, scene.camera, [lookup[n][0] for n in nodes], FRAMES, .25)
        bpy.context.view_layer.update()
        rotation = scene.camera.rotation_euler.to_matrix()
        center = Vector(scene.camera.location) + rotation @ Vector((0, 0, -1.0))
        extent = np.ptp(np.asarray(scene.camera.data.view_frame(scene=scene)), axis=0)
        experiments = [method for method in METHODS if method == "lbs" or any(method in snapshots[n] for n in nodes)]
        allowed = {bone for n in nodes for bone in rows[n]["bone_targets"]}
        for obj in skeleton.objects:
            obj.hide_render = obj.name not in allowed
        comparison = {"camera": {"position": (BASIS @ np.asarray(scene.camera.location)).tolist(),
                                  "target": (BASIS @ np.asarray(center)).tolist(),
                                  "up": (BASIS @ np.asarray(rotation @ Vector((0, 1, 0)))).tolist(),
                                  "width_m": extent[0], "height_m": extent[1], "size_px": [640, 420]},
                      "frames": list(FRAMES), "methods": {}}
        for method in experiments:
            clip = Clip(np.array(source["clock_s"])[list(FRAMES)])
            color, bone_color = clip.material("Muscle", [.51, .10, .081]), clip.material("Bone", [.70, .62, .47])
            items, checks = [], {}
            # Negative or group-only controls remain unchanged in both regional views.
            names = {n: snapshots[n].get(method, snapshots[n]["lbs"]) for n in nodes}
            for label, sequence, faces, material in [
                *((f"pilot-{node}", names[node], lookup[node][1], color) for node in nodes),
                *((f"bone-{name}", [gltf_world[i][name][0] for i in FRAMES], gltf_world[0][name][1], bone_color)
                  for name in sorted(allowed & gltf_world[0].keys())),
            ]:
                base = sequence[0] @ BASIS.T
                base_normals = normals(base, faces)
                index, prim = clip.mesh(label, "MUSCLES", base, faces, material)
                prim["targets"] = [{"POSITION": clip.accessor(p @ BASIS.T - base, "VEC3", bounds=True,
                                                              target=34962),
                                    "NORMAL": clip.accessor(normals(p @ BASIS.T, faces) - base_normals,
                                                            "VEC3", target=34962)}
                                   for p in sequence[1:]]
                clip.channel(index, "weights", np.eye(len(FRAMES))[:, 1:].ravel(), "SCALAR")
                if label.startswith("bone-"):
                    continue
                indices = np.linspace(0, len(base) - 1, min(len(base), 5), dtype=int)
                checks[label] = {"indices": indices.tolist(),
                                 "world_glb_m": [(p[indices] @ BASIS.T).tolist() for p in sequence],
                                 "viewport_uv": [[list(world_to_camera_view(
                                     scene, scene.camera, Vector(p))[:2]) for p in sample[indices]] for sample in sequence]}
                mesh = bpy.data.meshes.new(label)
                mesh.from_pydata(sequence[0].tolist(), [], faces.tolist())
                for poly in mesh.polygons:
                    poly.use_smooth = True
                obj = bpy.data.objects.new(label, mesh)
                target.objects.link(obj)
                source_obj = lookup[int(label.split("-")[1])][0]
                original_mat = source_obj.get("anatomical_material")
                mesh.materials.append(bpy.data.materials[original_mat] if original_mat else source_obj.data.materials[0])
                items.append((obj, sequence))
            glb = output / f"{region}-{method}.glb"
            clip.finish(glb)
            comparison["methods"][method] = {"file": glb.name, "sha256": digest(glb), "points": checks}
            for j, frame in enumerate(FRAMES):
                scene.frame_set(frame)
                for obj, sequence in items:
                    obj.data.vertices.foreach_set("co", sequence[j].astype(np.float32).ravel())
                    obj.data.update()
                still(scene, output / f"{region}-{method}-{frame:03d}.png")
            for obj, _ in items:
                bpy.data.objects.remove(obj, do_unlink=True)
        comparisons[region] = comparison
    dump(output / "comparison.json", {"run_id": source["run_id"], "motion_sha256": source["motion_sha256"],
                                      "mapping_revision_sha256": source["mapping_revision_sha256"],
                                      "crosswalk_revision": 3, "regions": comparisons})
    print("Rendered", len(comparisons), "region comparisons for the five exact states", flush=True)


if __name__ == "__main__":
    run(*(Path(p) for p in sys.argv[sys.argv.index("--") + 1:]))
