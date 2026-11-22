"""Audit and locally relax upper-limb atlas surfaces in an existing saved-state scene."""

from hashlib import sha256
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from atlas_arm_review_blender import ARM_BONES, check_arm_bone_pose, endpoint_distances, path_muscles
from atlas_arm_seams_blender import upper_limb_objects
from atlas_clearance_blender import bake_surface
from atlas_collision_blender import ATLAS, RECTUS, bone_surfaces, check_detector, rendered_meshes, surface, tree


ARCHIVE = "Upper limb · before local fold repair"
FIT = "Upper limb · local fold repair"
MAX_SHIFT_M = .004
MAX_ENDPOINT_CHANGE_M = .0005


def self_pairs(bvh, triangles, weld):
    pairs = np.asarray(bvh.overlap(bvh), dtype=np.int32).reshape(-1, 2)
    pairs = pairs[pairs[:, 0] < pairs[:, 1]]
    a, b = weld[triangles[pairs]].transpose(1, 0, 2)
    return pairs[~(a[:, :, None] == b[:, None, :]).any(axis=(1, 2))]


def self_check():
    check_detector()
    xyz = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                    [.25, .25, -.5], [.25, .25, .5], [.75, .1, 0.]])
    triangles = np.arange(6).reshape(2, 3)
    bvh = tree(xyz, triangles)
    assert self_pairs(bvh, triangles, np.arange(6)).tolist() == [[0, 1]]
    assert not len(self_pairs(bvh, triangles, np.array([0, 1, 2, 0, 4, 5])))
    xyz[3:] += 2
    assert not len(self_pairs(tree(xyz, triangles), triangles, np.arange(6)))


def topology(obj, triangles):
    rest = np.empty((len(obj.data.vertices), 3), np.float32)
    obj.data.vertices.foreach_get("co", rest.ravel())
    _, first, weld = np.unique(rest, axis=0, return_index=True, return_inverse=True)
    edges = weld[triangles[:, [0, 1, 1, 2, 2, 0]]].reshape(-1, 2)
    edges = np.unique(np.concatenate((edges, edges[:, ::-1])), axis=0)
    a, b = edges[edges[:, 0] != edges[:, 1]].T
    degree = np.maximum(np.bincount(a, minlength=len(first)), 1)
    return first, weld, a, b, degree


def relax(points, topo, mask, steps, cap):
    first, weld, a, b, degree = topo
    start = points[first]
    current = start.copy()
    for _ in range(steps):
        for scale in (.5, -.53):
            mean = np.column_stack([
                np.bincount(a, weights=current[b, axis], minlength=len(first)) / degree
                for axis in range(3)
            ])
            current += scale * (mean - current) * mask[:, None]
    delta = current - start
    delta *= (cap / np.maximum(np.linalg.norm(delta, axis=1), cap))[:, None]
    return (points + delta[weld]).astype(np.float32)


def endpoints(record, code):
    if code is None:
        return []
    paths = sorted((row for row in record["paths"] if row["actuator"] == code), key=lambda row: row["segment"])
    if not paths or [p["segment"] for p in paths] != list(range(len(paths))):
        raise ValueError(f"incomplete native path: {code}")
    return [paths[0]["start_m"], paths[-1]["end_m"]]


def collect(scene, expected, sources):
    groups = scene.collection.children
    visible = [o for layer in (ATLAS, RECTUS) for o in rendered_meshes(groups[layer])]
    native = {obj["source_label"]: code for code, obj in path_muscles(scene).items()}
    cached = {label: [] for label in sources}
    topologies = {}
    retained = {}
    for record in expected["frames"]:
        frame = record["frame"]
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        check_arm_bone_pose(record, graph)
        for row in (g for g in record["geoms"] if g["name"] in ARM_BONES):
            matrix = bpy.data.objects["Mesh_" + row["usd_name"]].evaluated_get(graph).matrix_world
            if not np.allclose(np.asarray(matrix)[:3, :3], row["rotation"], atol=2e-6, rtol=0):
                raise ValueError("upper-limb bone orientation differs from the saved state")
        poses = {o.get("source_label", o.name): surface(o, graph) for o in visible}
        if len(poses) != len(visible):
            raise ValueError("duplicate visible atlas labels")
        poses.update({label: surface(obj, graph) for label, obj in sources.items() if label not in poses})
        retained[frame] = {
            label: sha256(points.tobytes() + faces.tobytes()).hexdigest()
            for label, (points, faces) in poses.items()
        }
        bounds = {label: (pts.min(0), pts.max(0)) for label, (pts, _) in poses.items()}
        bones = bone_surfaces(groups["bones"].objects, graph)
        trees = {}
        for label, obj in sources.items():
            points, triangles = poses[label]
            if frame == 0:
                topologies[label] = topology(obj, triangles)
            first, weld, *_ = topologies[label]
            lo, hi = bounds[label]
            margin = 2 * MAX_SHIFT_M + .0001
            lo, hi = lo - margin, hi + margin
            neighbors = [(("bone", name), bvh) for name, low, high, bvh in bones
                         if (hi >= low).all() and (high >= lo).all()]
            for other, (low, high) in bounds.items():
                if other == label or (hi < low).any() or (high < lo).any():
                    continue
                if other not in trees:
                    trees[other] = tree(*poses[other])
                neighbors.append((("surface", other), trees[other]))
            if label not in trees:
                trees[label] = tree(points, triangles)
            bvh = trees[label]
            refs = endpoints(record, native.get(label))
            pin = np.ones(len(first))
            if refs:
                distances = np.linalg.norm(points[first, None] - np.asarray(refs)[None], axis=2).min(axis=1)
                pin = ((distances - .012) / .016).clip(0, 1)
            cached[label].append((points, triangles, neighbors, {key: bvh.overlap(n) for key, n in neighbors},
                                  self_pairs(bvh, triangles, weld), refs, endpoint_distances(bvh, refs), pin))
    return cached, topologies, retained


def compare(points, row, topo, other=None):
    before, triangles, neighbors, previous, original_self, refs, distances, _ = row
    bvh = tree(points, triangles)
    new_self = self_pairs(bvh, triangles, topo[1])
    risk = []
    if len(new_self) > len(original_self):
        risk.extend(new_self.ravel())
    counts = {"bone": [0, 0], "surface": [0, 0]}
    for key, neighbor in neighbors:
        original = previous[key]
        changed = bvh.overlap((other or {}).get(key, neighbor))
        if len(changed) > len(original):
            risk.extend(index for index, _ in original)
            risk.extend(index for index, _ in changed)
        counts[key[0]][0] += len(original)
        counts[key[0]][1] += len(changed)
    endpoint_change = 0.
    for ref, before_distance in zip(refs, distances, strict=True):
        _, _, face, distance = bvh.find_nearest(Vector(ref))
        change = distance - before_distance
        endpoint_change = max(change, endpoint_change)
        if change > MAX_ENDPOINT_CHANGE_M:
            risk.append(face)
    result = {
        "self_pairs": [len(original_self), len(new_self)],
        "bone_pairs": counts["bone"],
        "neighbor_pairs": counts["surface"],
        "max_endpoint_distance_increase_m": endpoint_change,
        "max_displacement_m": float(np.linalg.norm(points - before, axis=1).max()),
    }
    return risk, result


def fit(rows, topo):
    first, weld, a, b, _ = topo
    mask = np.zeros(len(first))
    for points, triangles, _, _, hits, *_ in rows:
        if np.linalg.norm(points - points[first][weld], axis=1).max() > 1e-6:
            return []
        mask[weld[triangles[hits]].ravel()] = 1.
    if not mask.any():
        return []
    for _ in range(2):
        np.maximum.at(mask, a, .6 * mask[b])
    candidates = []
    for steps, cap in ((4, MAX_SHIFT_M), (2, .002), (1, MAX_SHIFT_M)):
        region = mask.copy()
        for _ in range(5):
            poses = [relax(row[0], topo, region * row[-1], steps, cap) for row in rows]
            compared = [compare(points, row, topo) for points, row in zip(poses, rows, strict=True)]
            risk = [i for violations, _ in compared for i in violations]
            if not risk:
                gain = sum(r["self_pairs"][0] - r["self_pairs"][1] for _, r in compared)
                if gain > 0:
                    candidates.append((gain, poses))
                break
            # Keep a single protection mask across the entire animation.
            blocked = weld[rows[0][1][np.asarray(risk, dtype=np.int32)]].ravel()
            if not region[blocked].any():
                break
            region[blocked] = 0.
    return sorted(candidates, key=lambda item: item[0], reverse=True)


def audit_selected(cached, topologies, selected):
    all_frames = [{} for _ in next(iter(cached.values()))]
    by_frame = [
        {("surface", label): tree(points[i], cached[label][i][1]) for label, points in selected.items()}
        for i in range(len(all_frames))
    ]
    for label, poses in selected.items():
        first, weld, *_ = topologies[label]
        for i, (points, row) in enumerate(zip(poses, cached[label], strict=True)):
            risk, result = compare(points, row, topologies[label], by_frame[i])
            if (risk or result["max_displacement_m"] > MAX_SHIFT_M + 1e-6
                    or np.linalg.norm(points - points[first][weld], axis=1).max() > 1e-6):
                raise ValueError(f"surface acceptance failed for {label}, frame {i}")
            all_frames[i][label] = result
    return all_frames


def select(cached, topologies):
    candidates = {label: fit(rows, topologies[label]) for label, rows in cached.items()}
    selected = {}
    selected_trees = {}
    order = sorted((label for label, options in candidates.items() if options),
                   key=lambda label: (-candidates[label][0][0], label))
    for label in order:
        for _, poses in candidates[label]:
            valid = True
            pose_trees = []
            for i, (points, row) in enumerate(zip(poses, cached[label], strict=True)):
                target_bvh = tree(points, row[1])
                pose_trees.append(target_bvh)
                for other, _ in row[2]:
                    if other not in selected_trees:
                        continue
                    neighbor = selected_trees[other][i]
                    if len(target_bvh.overlap(neighbor)) > len(row[3][other]):
                        valid = False
                        break
                if not valid:
                    break
            if valid:
                selected[label] = poses
                selected_trees["surface", label] = pose_trees
                break
    if not selected:
        raise ValueError("no upper-limb surface accepted")
    return selected


def unchanged_digest(poses, changed):
    return sha256(json.dumps({k: v for k, v in poses.items() if k not in changed},
                             sort_keys=True).encode()).hexdigest()


def native_digest(scene):
    digests = []
    bones = scene.collection.children["bones"]
    for i in range(scene.frame_end + 1):
        scene.frame_set(i)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        digest = sha256()
        for obj in sorted(rendered_meshes(bones), key=lambda obj: obj.name):
            points, faces = surface(obj, graph)
            digest.update(obj.name.encode() + points.tobytes() + faces.tobytes())
        digests.append(digest.hexdigest())
    return digests


def verify(scene, expected, folder):
    report = json.loads((folder / "surface-repair.json").read_text())
    repaired = set(report["repaired_surfaces"])
    source_objects = [*upper_limb_objects(scene), *path_muscles(scene).values()]
    sources = {obj["source_label"]: obj for obj in source_objects}
    cached, topologies, baseline = collect(scene, expected, sources)
    native = native_digest(scene)
    bpy.ops.wm.open_mainfile(filepath=str(folder / "arm-surfaces.blend"), use_scripts=False)
    scene = bpy.context.scene
    if native != native_digest(scene):
        raise ValueError("native skeletal geometry changed on reopen")
    layers = scene.collection.children
    active = {obj.get("source_label", obj.name): obj
              for layer in (ATLAS, RECTUS) for obj in rendered_meshes(layers[layer])}
    selected = {label: [] for label in repaired}
    for record in expected["frames"]:
        i = record["frame"]
        scene.frame_set(i)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        unchanged = {}
        for label, obj in active.items():
            points, faces = surface(obj, graph)
            if label in repaired:
                if not np.array_equal(faces, cached[label][i][1]):
                    raise ValueError(f"triangle indices changed for {label}")
                selected[label].append(points)
            else:
                unchanged[label] = sha256(points.tobytes() + faces.tobytes()).hexdigest()
        if unchanged_digest(unchanged, repaired) != unchanged_digest(baseline[i], repaired):
            raise ValueError(f"uncorrected atlas geometry changed at frame {i}")
    results = audit_selected(cached, topologies, selected)
    for i, rows in enumerate(results):
        for label, result in rows.items():
            original = report["frames"][i]["repaired"][label]
            if any(result[metric] != original[metric] for metric in ("self_pairs", "bone_pairs", "neighbor_pairs")):
                raise ValueError(f"intersection counts changed on reopen for {label}, frame {i}")
    return {"status": "PASS", "sample_count": len(results), "reopened_surface_count": len(repaired),
            "unchanged_atlas_surface_count": len(active) - len(repaired),
            "native_bone_checksums": native}


def run(scene, expected, output):
    self_check()
    records = expected["frames"]
    if [r["frame"] for r in records] != list(range(scene.frame_end + 1)):
        raise ValueError("surface inputs do not describe this timeline")
    atlas = scene.collection.children[ATLAS]
    source_objects = [*upper_limb_objects(scene), *path_muscles(scene).values()]
    sources = {obj["source_label"]: obj for obj in source_objects}
    cached, topologies, retained = collect(scene, expected, sources)
    selected = select(cached, topologies)
    results = audit_selected(cached, topologies, selected)
    archive = bpy.data.collections.new(ARCHIVE)
    fitted = bpy.data.collections.new(FIT)
    atlas.children.link(archive)
    atlas.children.link(fitted)
    for label, poses in selected.items():
        original = sources[label]
        new = bake_surface(original, fitted, range(len(records)), poses)
        for key, value in original.items():
            new[key] = value
        new["correction"] = "Bounded local surface relaxation with per-frame intersection and landmark checks"
        for group in list(original.users_collection):
            group.objects.unlink(original)
        archive.objects.link(original)
    archive.hide_render = True
    bpy.context.view_layer.layer_collection.children[ATLAS].children[ARCHIVE].hide_viewport = True
    scene.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "arm-surfaces.blend"), compress=True)
    hd_source = bpy.data.texts.get("Full-resolution arm source · evidence")
    return {
        "status": "ILLUSTRATIVE_SURFACE_REPAIR",
        "source_run_id": expected["run_id"],
        "model": expected["model"],
        "source_files": expected["source_files"],
        "sources": [
            json.loads(hd_source.as_string()) if hd_source else "MyoSuite adapted BodyParts3D, fullbody_atlas_light.glb",
            "Saved MS-Human-700 replay",
        ],
        "parameters": {"maximum_displacement_m": MAX_SHIFT_M,
                       "maximum_endpoint_distance_increase_m": MAX_ENDPOINT_CHANGE_M},
        "limitations": "Triangle-pair counts depend on tessellation. No penetration depth, biological attachment or tissue mechanics was validated.",
        "repaired_surfaces": sorted(selected),
        "audited_surfaces": sorted(sources),
        "frames": [
            {"frame": i, "source_index": record["source_index"], "state_sha256": record["state_sha256"],
             "time_s": record["time_s"],
             "self_pairs_before": {label: len(rows[i][4]) for label, rows in cached.items()},
             "repaired": results[i], "unchanged_atlas_mesh_sha256": unchanged_digest(retained[i], selected)}
            for i, record in enumerate(records)
        ],
    }


if __name__ == "__main__":
    folder, mapping, *mode = sys.argv[sys.argv.index("--") + 1:]
    folder, mapping = Path(folder), Path(mapping)
    mapping_bytes = mapping.read_bytes()
    expected = json.loads(mapping_bytes)
    mapping_sha256 = sha256(mapping_bytes).hexdigest()
    if mode == ["verify"]:
        report = json.loads((folder / "surface-repair.json").read_text())
        if report["mapping_sha256"] != mapping_sha256:
            raise ValueError("verification requires the original mapping")
        data = verify(bpy.context.scene, expected, folder)
        name = "surface-reopen.json"
    elif not mode:
        data = run(bpy.context.scene, expected, folder)
        name = "surface-repair.json"
    else:
        raise ValueError("expected no mode or 'verify'")
    data["mapping_sha256"] = mapping_sha256
    (folder / name).write_text(json.dumps(data, indent=2))
