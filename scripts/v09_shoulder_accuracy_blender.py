"""Probe attachment-aware FJ1447 registration on exact, saved shoulder frames."""

import argparse
import hashlib
import heapq
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_arm_surface_blender import MAX_SHIFT_M, self_check
from atlas_collision_blender import tree
from v09_motion_qa_blender import measure


BONE_IDS = {"clavicle": "FJ3362", "humerus": "FJ3368"}
SITES = ("PECM1_r-P4", "PECM1_r-P1")
SURFACE_GAP_M = 0.0005
LOCAL_FALLOFF_MM = 75.0


def spatial(points, faces):
    return points.min(0), points.max(0), tree(points, faces)


def geodesic(raw, edges, weld, seeds):
    adjacency = [[] for _ in raw]
    for a, b in edges:
        length = float(np.linalg.norm(raw[a] - raw[b]))
        adjacency[a].append((b, length))
        adjacency[b].append((a, length))
    distance = np.full(len(raw), np.inf)
    queue = [(0.0, int(i)) for i in np.unique(weld[seeds])]
    distance[[i for _, i in queue]] = 0
    heapq.heapify(queue)
    while queue:
        length, index = heapq.heappop(queue)
        if length > distance[index]:
            continue
        for neighbour, step in adjacency[index]:
            candidate = length + step
            if candidate < distance[neighbour]:
                distance[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))
    defined = np.flatnonzero(np.isfinite(distance))
    unvisited = np.flatnonzero(~np.isfinite(distance))
    # shortcut: inherit distance at small disconnected OBJ fragments, replace if anatomical seam labels become available.
    for index in unvisited:
        gaps = np.linalg.norm(raw[defined] - raw[index], axis=1)
        closest = np.argmin(gaps)
        distance[index] = distance[defined[closest]] + gaps[closest]
    return distance[weld], len(unvisited)


def local_basis(direction, anterior):
    forward = direction / np.linalg.norm(direction)
    transverse = anterior - forward * (forward @ anterior)
    transverse /= np.linalg.norm(transverse)
    return np.column_stack((forward, transverse, np.cross(forward, transverse)))


def attach_patches(raw_muscle, structures, start, sites):
    patches, selected, bone_distances = [], [], []
    for bone, site in zip(BONE_IDS.values(), SITES, strict=True):
        asset = structures[bone]
        mesh = tree(np.asarray(asset["vertices_mm"]), np.asarray(asset["faces"]))
        distances = np.asarray([mesh.find_nearest(Vector(p))[3] for p in raw_muscle])
        patch = np.flatnonzero(distances <= np.quantile(distances, .05))
        matrix = np.asarray(start["transforms"][bone]["matrix"])
        projected = raw_muscle[patch] @ matrix[:3, :3].T + matrix[:3, 3]
        patches.append(patch)
        selected.append(int(patch[np.argmin(np.linalg.norm(projected - sites[site], axis=1))]))
        bone_distances.append(distances)
    if np.intersect1d(*patches).size:
        raise ValueError("source origin and insertion patches overlap")
    return patches, selected, bone_distances


def distances(points, mesh):
    locations = [mesh.find_nearest(Vector(p)) for p in points]
    unsigned = np.asarray([distance for _, _, _, distance in locations])
    nearest = np.asarray([list(position) for position, _, _, _ in locations])
    normals = np.asarray([list(normal) for _, normal, _, _ in locations])
    signed = np.sum((points - nearest) * normals, axis=1)
    return unsigned, signed


def metrics(points, faces, weld, native, display, sites, patches, selected, baseline_edge, edges, side):
    result = measure(points, faces, weld, native, sites)
    result["display_bone_crossing_pairs"] = measure(points, faces, weld, display, {})["bone_triangle_crossing_pairs"]
    result["model_anchor_vertex_distance_m"] = {
        site: float(np.linalg.norm(points[index] - sites[site]))
        for site, index in zip(SITES, selected, strict=True)}
    result["attachment_patch_and_inward_distance"] = {}
    for collection, meshes in (("native", native), ("display", display)):
        for patch, (name, _, _, mesh) in zip(patches, meshes[:2], strict=True):
            unsigned, signed = distances(points, mesh)
            result["attachment_patch_and_inward_distance"][collection + "_" + name] = {
                "patch_median_surface_distance_m": float(np.median(unsigned[patch])),
                "inward_nearest_vertex_proxy_m": float(max(0, -signed.min())),
            }
    lengths = np.linalg.norm(points[edges[:, 1]] - points[edges[:, 0]], axis=1)
    ratios = lengths / baseline_edge
    result["edge_ratio_vs_v08_p01_p99"] = np.quantile(ratios, [.01, .99]).tolist()
    result["min_triangle_area_m2"] = float(np.linalg.norm(np.cross(
        points[faces[:, 1]] - points[faces[:, 0]], points[faces[:, 2]] - points[faces[:, 0]]), axis=1).min() / 2)
    result["median_patient_right_distance_m"] = float(np.median((points - side[0]) @ side[1]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("motion", type=Path)
    parser.add_argument("qa", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    motion, qa = (json.loads(p.read_text()) for p in (args.motion, args.qa))
    structures = motion["structures"]
    asset = structures["FJ1447"]
    if asset["fma_id"] != "FMA34690" or any(structures[fj]["patient_side"] != "right" for fj in BONE_IDS.values()):
        raise ValueError("unexpected source muscle or laterality")
    self_check()
    raw_muscle, faces = np.asarray(asset["vertices_mm"]), np.asarray(asset["faces"])
    raw, first, weld = np.unique(raw_muscle, axis=0, return_index=True, return_inverse=True)
    edges = np.unique(np.sort(np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    edges = edges[weld[edges[:, 0]] != weld[edges[:, 1]]]
    welded_edges = np.unique(np.sort(weld[edges], axis=1), axis=0)
    start_sites = qa["frames"][0]["attachment_sites_m"]
    patches, selected, source_distances = attach_patches(raw_muscle, structures, motion["frames"][0], start_sites)
    start, end = selected
    (start_distance, origin_fragments), (end_distance, insertion_fragments) = (
        geodesic(raw, welded_edges, weld, patch) for patch in patches)
    geodesic_weight = (start_distance / (start_distance + end_distance))[:, None]
    local_distance, anchor_fragments = geodesic(raw, welded_edges, weld, [end])
    local = np.clip(1 - local_distance / LOCAL_FALLOFF_MM, 0, 1)
    local = (local * local * (3 - 2 * local))[:, None]
    source_axis = raw_muscle[end] - raw_muscle[start]
    source_basis = local_basis(source_axis, np.array([0., -1., 0.]))
    source_local = (raw_muscle - raw_muscle[start]) @ source_basis / 1000
    source_axis_length = np.linalg.norm(source_axis) / 1000
    route = None
    if args.routing:
        route = json.loads(args.routing.read_text())
        if route["run_id"] != motion["run_id"]:
            raise ValueError("route source run mismatch")
        first_sites = route["frames"][0]["sites"]
        route_distance = np.linalg.norm(np.subtract(first_sites["PECM1_r-P2"]["point_m"],
                                                    first_sites[SITES[1]]["point_m"])) * 1000
        guide_vertices = np.flatnonzero((abs(local_distance - route_distance) <= 2.5)
                                        & ((raw_muscle - raw_muscle[end]) @ -source_axis > 0))
        if not guide_vertices.size:
            raise ValueError("source near-insertion section missing")
    result, buffers = [], {}
    for frame, q in zip(motion["frames"], qa["frames"], strict=True):
        if any(frame[k] != q[k] for k in ("state_index", "frame_time", "state_sha256")):
            raise ValueError("frame identity mismatch")
        index = frame["state_index"]
        baseline = np.asarray(frame["surface"]["FJ1447"]["vertices_m"])
        if not np.array_equal(baseline, q["variant_vertices_m"]["v08_clipped_two_bone"]):
            raise ValueError("baseline surface mismatch")
        anchors = frame["joint_anchors_m"]
        right, left = [np.asarray(anchors[f"shoulder_elv_{s}"]["position_m"]) for s in "rl"]
        side = (right + left) / 2, (right - left) / np.linalg.norm(right - left)
        sites = q["attachment_sites_m"]
        native = [(name, *spatial(np.asarray(q["native_bones"][name]["vertices_m"]),
                                  np.asarray(q["native_bones"][name]["faces"])))
                  for name in (*BONE_IDS, "scapula")]
        display, rigid_muscle = [], []
        for name, fj in BONE_IDS.items():
            matrix = np.asarray(frame["transforms"][fj]["matrix"])
            transform = matrix[:3, :3] * 1000
            if not np.allclose(transform @ transform.T, np.eye(3), atol=1e-10, rtol=0) or np.linalg.det(transform) <= 0:
                raise ValueError("nonproper bone transform")
            bone = structures[fj]
            vertices = np.asarray(bone["vertices_mm"]) @ matrix[:3, :3].T + matrix[:3, 3]
            display.append((name, *spatial(vertices, np.asarray(bone["faces"]))))
            rigid_muscle.append(raw_muscle @ matrix[:3, :3].T + matrix[:3, 3])
        clavicle, humerus = rigid_muscle
        humeral_near, humeral_normal, _, _ = native[1][-1].find_nearest(Vector(sites[SITES[1]]))
        target = np.asarray(humeral_near + SURFACE_GAP_M * humeral_normal)
        distal_shift = target - humerus[end]
        target_axis = target - clavicle[start]
        axis_scale = float(np.linalg.norm(target_axis) / source_axis_length)
        clavicle_matrix = np.asarray(frame["transforms"]["FJ3362"]["matrix"])
        basis = local_basis(target_axis, -clavicle_matrix[:3, 1] * 1000)
        baseline_edge = np.linalg.norm(baseline[edges[:, 1]] - baseline[edges[:, 0]], axis=1)
        variants = {
            "v08_control": baseline,
            "distal_local_taper": baseline + local * (target - baseline[end]),
            "bounded_distal_taper": baseline + local * (target - baseline[end])
                                  * min(1., MAX_SHIFT_M / np.linalg.norm(target - baseline[end])),
            "geodesic_control": clavicle + geodesic_weight * (humerus - clavicle),
            "geodesic_with_distal_anchor": clavicle + geodesic_weight * (humerus + distal_shift - clavicle),
            "two_site_axial": (source_local * [axis_scale, 1., 1.]) @ basis.T + clavicle[start],
        }
        if route:
            match, = (r for r in route["frames"] if r["state_index"] == index)
            if any(match[k] != frame[k] for k in ("frame_time", "state_sha256")):
                raise ValueError("route sample mismatch")
            p2 = np.asarray(match["sites"]["PECM1_r-P2"]["point_m"])
            if match["sites"]["PECM1_r-P2"]["body"] != "humerus_r":
                raise ValueError("unexpected humeral guide body")
            origin = baseline[end]
            guide = baseline[guide_vertices].mean(axis=0)
            rotation = np.asarray(Vector(guide - origin).rotation_difference(Vector(p2 - target)).to_matrix())
            if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6, rtol=0) or np.linalg.det(rotation) <= 0:
                raise ValueError("invalid route rotation")
            reoriented = (baseline - origin) @ rotation.T + target
            variants["distal_route_taper"] = baseline + local * (reoriented - baseline)
        for name, points in variants.items():
            if not np.isfinite(points).all():
                raise ValueError(f"invalid {name} coordinates")
            buffers[f"{name}_{index}"] = points
        result.append({
            "state_index": index, "frame_time": frame["frame_time"], "state_sha256": frame["state_sha256"],
            "external_humeral_target_m": target.tolist(), "site_offset_to_target_m": float(
                np.linalg.norm(target - sites[SITES[1]])), "axial_scale": axis_scale,
            "variants": {name: metrics(points, faces, weld, native, display, sites, patches, selected,
                                       baseline_edge, edges, side) for name, points in variants.items()},
        })
    args.output.mkdir()
    with (args.output / "variants.npz").open("xb") as output:
        np.savez_compressed(output, faces=faces, **buffers)
    with (args.output / "metrics.json").open("x") as output:
        json.dump({"run_id": motion["run_id"], "motion_sha256": hashlib.sha256(args.motion.read_bytes()).hexdigest(),
                   "qa_input_sha256": hashlib.sha256(args.qa.read_bytes()).hexdigest(),
                   "blender_version": bpy.app.version_string, "raw_source_vertices": len(raw_muscle),
                   "raw_unique_vertices": len(first), "relative_source_attachment_percentile": .05,
                   "distance_inherited_at_disconnected_vertices": [origin_fragments, insertion_fragments, anchor_fragments],
                   "external_surface_margin_m": SURFACE_GAP_M, "local_taper_cutoff_mm": LOCAL_FALLOFF_MM,
                   "source_anchor_vertex_indices": selected,
                   "source_anchor_to_atlas_bone_distance_mm": [float(d[i]) for d, i in zip(source_distances, selected)],
                   "source_attachment_patch_members": [p.tolist() for p in patches], "frames": result},
                  output, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
