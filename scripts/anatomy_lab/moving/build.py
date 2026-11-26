"""Build one local, reproducible whole-body clip from pinned saved integration states."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter

import mujoco as mj
import numpy as np

from atlas_reference import ASSETS, REVISION, verify
from human_models_mcp.atlas import atlas_lock, verify_asset
from human_models_mcp.atlas_registration import native_bone, nearest, rigid_fit
from human_models_mcp.rectus import SOURCE as Z_SOURCE, register as rectus_register, segment_frame, skin as rectus_skin
from human_models_mcp.scene_export import load_saved_run, restore_state
from glb import B4, BASIS, Clip, array, face_vectors, unpack
from contact_overlay import experimental_overlays, floor_events


LIMIT = .00005
MYOSIM_TREE = "8e504f094e91e8b453982f41c25d6c1013055ddd9a84078e34bd7ca974926175"
CATALOG_SHA = "953a632513863a62fb65c8468ec16cee6cb195f4899516fbb254d10a6b5fe32c"
TRIAL_BONES = {"FJ3362": "clavicle", "FJ3368": "humerus", "FJ3152": "r_pelvis",
               "FJ3365": "r_femur", "FJ3259": "l_femur"}
CAMERAS = {
    "side": {"position": [.84, .42, 2.91], "target": [.84, .31, 0], "fov": 37},
    "oblique": {"position": [2.38, 1.13, 2.56], "target": [.83, .29, 0], "fov": 36},
    "torso": {"position": [1.99, .86, 1.24], "target": [1.21, .29, 0], "fov": 35},
}
LAYERS = {
    "BODY": {"mode": "registered_rigid", "available": True, "description": "World floor at z=0"},
    "SKELETON": {"mode": "registered_rigid", "available": True, "description": "Native MS-Human-700 bone geometry"},
    "MUSCLES": {"mode": "skinned_illustrative", "available": True, "description": "Source meshes, constant materials"},
    "ORGANS": {"mode": "static_reference_only", "available": False, "description": "Available in the static atlas"},
    "SKIN": {"mode": "static_reference_only", "available": False, "description": "Available in the static atlas"},
    "OVERLAYS": {"mode": "registered_rigid", "available": True, "description": "Native spherical contact pads"},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def matrix(rotation, translation):
    out = np.eye(4)
    out[:3, :3], out[:3, 3] = np.asarray(rotation).reshape(3, 3), translation
    return out


def geom_pose(data, geom):
    return matrix(data.geom_xmat[geom], data.geom_xpos[geom])


def mesh_pose(model, mesh):
    rotation = np.zeros(9)
    mj.mju_quat2Mat(rotation, model.mesh_quat[mesh])
    return matrix(rotation, model.mesh_pos[mesh])


def geometry(model, mesh):
    v, f = model.mesh_vertadr[mesh], model.mesh_faceadr[mesh]
    return (model.mesh_vert[v:v + model.mesh_vertnum[mesh]],
            model.mesh_face[f:f + model.mesh_facenum[mesh]])


def apply(transform, points):
    return np.einsum("...ij,...j->...i", transform[..., :3, :3], points) + transform[..., :3, 3]


def visible_geoms(model):
    return [g for g in range(model.ngeom)
            if model.geom_type[g] == mj.mjtGeom.mjGEOM_MESH and model.geom_rgba[g, 3] > 0]


def joint_matches(doc, blob, model, geoms):
    import myo_sim

    source = myo_sim.load_model("myofullbody")
    data = mj.MjData(source)
    mj.mj_forward(source, data)
    skin = doc["skins"][0]
    inv = array(doc, blob, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    bind = np.linalg.inv(inv.astype(float))
    lookup = {}
    for g in geoms:
        lookup.setdefault(model.mesh(model.geom_dataid[g]).name, []).append(g)
    result, matches = [], {}
    for joint, node in enumerate(skin["joints"]):
        name = doc["nodes"][node]["name"]
        orig = int(re.search(r"_id(\d+)_geom$", name)[1])
        sid = source.geom_dataid[orig]
        mesh_name = source.mesh(sid).name
        aliases = {mesh_name, re.sub(r"^[a-z0-9]+_geom_1_", "", mesh_name)}
        if mesh_name == "torso_geom_1_thoracic12_s":
            aliases.add("thoracic12")
        if mesh_name.endswith(("_r", "_l")):
            alias = mesh_name[:-2] + ("_mirror" if mesh_name.endswith("_l") else "")
            aliases.update((alias, "hand_" + alias))
        source_points = apply(mesh_pose(source, sid), geometry(source, sid)[0])
        source_raw = geom_pose(data, orig) @ np.linalg.inv(mesh_pose(source, sid))
        center_error = float(np.linalg.norm(bind[joint, :3, 3] - BASIS @ data.geom_xpos[orig]))
        distances = {}
        for g in sorted({g for alias in aliases for g in lookup.get(alias, [])}):
            mid = model.geom_dataid[g]
            points = apply(mesh_pose(model, mid), geometry(model, mid)[0])
            distances[g] = float(max(nearest(source_points, points)[1].max(),
                                     nearest(points, source_points)[1].max()))
        eligible = [g for g, distance in distances.items() if distance <= LIMIT]
        row = {"joint": joint, "label": name, "source_geom": source.geom(orig).name, "source_mesh": mesh_name,
               "source_raw_mesh_vertex_sha256": sha(source_points.astype("<f8").tobytes()),
               "source_raw_to_world_m": source_raw.tolist(), "source_bind_glb": bind[joint].tolist(),
               "source_bind_origin_error_m": center_error,
               "candidate_local_mesh_distances_m": {model.geom(g).name: d for g, d in distances.items()},
               "target": None}
        if center_error <= LIMIT and len(eligible) == 1:
            g = eligible[0]
            b = model.body(model.geom_bodyid[g]).name
            side = re.search(r"_([rl])_id", name)
            if side and b.endswith(("_l", "_r")) and b[-1] != side[1]:
                raise ValueError("swapped joint side")
            row["target"] = {"geom": model.geom(g).name, "body": b,
                             "local_mesh_distance_m": distances[g]}
            raw_from_geom = np.linalg.inv(mesh_pose(model, model.geom_dataid[g]))
            matches[joint] = (g, raw_from_geom @ np.linalg.inv(source_raw))
        result.append(row)
    return inv, bind, result, matches


def source_identity(label, bp):
    fj = re.search(r"\[(FJ\d+M?)\]$", label)
    obj = bp.get(fj[1], {}) if fj else {}
    return {"fj_id": fj[1] if fj else None, "bp_id": obj.get("bp_id"),
            "fma_id": f"FMA{obj['fma_id']}" if obj else None,
            "crosswalk": obj.get("identity_status", "unmapped_source_id")}


def bones_probe(args, model, neutral, bp, poses, times, selected, folder):
    basis = np.asarray(atlas_lock()["source_coordinates"]["world_basis"])
    # All fits use a proper rigid transform after a fixed mm-to-m basis conversion.
    if np.linalg.det(basis) != 1:
        raise ValueError("BodyParts3D basis must be proper")
    probe = Clip(times[selected])
    native_material = probe.material("Native", [.70, .62, .47])
    bp_material = probe.material("Trial fit", [.06, .42, .57])
    rows = {}
    for fj, name in TRIAL_BONES.items():
        obj = bp[fj]
        path = args.atlas / "meshes" / obj["filename"]
        verify_asset(path, obj)
        vertices, triangles = [], []
        for line in path.read_text().splitlines():
            fields = line.split()
            if fields and fields[0] == "v":
                vertices.append([float(v) for v in fields[1:]])
            if fields and fields[0] == "f":
                triangles.append([int(v.split("/")[0]) - 1 for v in fields[1:]])
        raw, faces = np.asarray(vertices), np.asarray(triangles)
        if (raw.shape != (len(raw), 3) or faces.shape != (len(faces), 3)
                or not np.isfinite(raw).all() or faces.min() < 0 or faces.max() >= len(raw)
                or not 50 <= np.ptp(raw, axis=0).max() <= 600):
            raise ValueError("invalid trial bone source geometry")
        original_faces = len(faces)
        faces = clean_faces(raw, faces)
        source = raw @ basis.T / 1000
        target = native_bone(model, neutral, name)
        s = source[np.linspace(0, len(source) - 1, min(1500, len(source)), dtype=int)]
        t = target[np.linspace(0, len(target) - 1, min(1500, len(target)), dtype=int)]
        rotation, offset = np.eye(3), t.mean(0) - s.mean(0)
        before = s + offset
        for _ in range(25):
            matched, d = nearest(t, s @ rotation + offset)
            keep = d <= np.quantile(d, .9)
            rotation, offset = rigid_fit(s[matched[keep]], t[keep])
        after = s @ rotation + offset
        extremes = np.array([np.argmin(t[:, 2]), np.argmax(t[:, 2])])
        geom = model.geom(name).id
        bind_local = np.linalg.inv(geom_pose(neutral, geom)) @ matrix(rotation.T @ basis / 1000, offset)
        def rms(values):
            return float(np.sqrt(np.mean(values ** 2)))

        rows[fj] = {"identity": obj, "target_geom": name, "target_body": model.body(model.geom_bodyid[geom]).name,
                    "native_rmse_before_m": rms(nearest(t, before)[1]),
                    "native_rmse_after_m": rms(nearest(t, after)[1]),
                    "atlas_rmse_after_m": rms(nearest(after, t)[1]),
                    "long_axis_endpoint_proxy_m": nearest(after, t[extremes])[1].tolist(),
                    "native_extrema_sample_indices": extremes.tolist(),
                    "rotation_determinant": float(np.linalg.det(rotation)),
                    "source_mm_to_native_geom_m": bind_local.tolist(),
                    "ground_min_m": float(min(apply(poses[geom][i] @ bind_local, raw)[:, 2].min()
                                              for i in selected)),
                    "removed_degenerate_faces": original_faces - len(faces), "status": "EXPERIMENT_ONLY"}
        points, native_faces = geometry(model, model.geom_dataid[geom])
        for label, vertices, triangles, material, xf in (
            (name, points, clean_faces(points, native_faces), native_material, np.eye(4)),
            (fj + "_fit", apply(bind_local, raw), faces, bp_material, np.eye(4)),
            (fj + "_before", apply(np.linalg.inv(geom_pose(neutral, geom)), source + t.mean(0) - s.mean(0)),
             faces, bp_material, np.eye(4)),
        ):
            node, _ = probe.mesh(label, "SKELETON", vertices @ BASIS.T, triangles, material)
            probe.transforms(node, B4 @ poses[geom][selected] @ xf @ B4.T)
    probe.finish(folder / "bp3d-probe.glb")
    return rows


def clean_faces(points, faces):
    return faces[np.linalg.norm(face_vectors(points, faces), axis=1) > 1e-13]


def samples_record(label, node, expected, out, indices=None):
    if indices is None:
        indices = np.unique(np.linspace(0, expected.shape[1] - 1, min(expected.shape[1], 5), dtype=int))
    out.append({"node": node, "name": label, "vertices": indices.tolist(), "world_glb_m": expected.tolist()})


def metrics(points, deformed, reference, faces):
    tri = deformed[:, faces, :]
    crosses = np.count_nonzero((tri[..., 1].min(2) < 0) & (tri[..., 1].max(2) >= 0), axis=1)
    base = face_vectors(points, faces)
    vectors = face_vectors(deformed, faces)
    tri_volume = np.sum(tri[:, :, 0] * vectors, axis=-1) / 6
    return {"min_height_m": deformed[..., 1].min(axis=1).tolist(),
            "floor_crossings": crosses.tolist(),
            "unsigned_net_triangle_volume_m3": np.abs(tri_volume.sum(axis=1)).tolist(),
            "small_area_proxy_faces": (np.linalg.norm(vectors, axis=-1) < 1e-11).sum(axis=1).tolist(),
            "orientation_proxy_faces": (np.sum(vectors * reference(base), axis=-1) < 0).sum(axis=1).tolist()}


def muscle_meshes(clip, source, blob, bp, matches, deltas, mats, sample, times, indices, folder, floor_z):
    rows, qa, variant = [], {}, {}
    start = perf_counter()
    for source_node, node in enumerate(source["nodes"]):
        if "mesh" not in node:
            continue
        name = node["name"]
        mesh = source["meshes"][node["mesh"]]["primitives"][0]
        points, joints, weights = [array(source, blob, mesh["attributes"][key])
                                    for key in ("POSITION", "JOINTS_0", "WEIGHTS_0")]
        faces = array(source, blob, mesh["indices"]).reshape(-1, 3)
        influences = sorted(int(j) for j in np.unique(joints[weights > 0]))
        cardiac = "papillary" in name.lower()
        missing = sorted(set(influences) - matches.keys())
        mode = "unmapped" if missing or cardiac else "skinned_illustrative"
        color = ("chest" if "pectoralis" in name.lower() else "muscle")
        row = {"name": name, **source_identity(name, bp), "dataset": "myosuite", "source_node": source_node,
               "source_mesh_sha256": sha(points.tobytes() + faces.tobytes() + joints.tobytes() + weights.tobytes()),
               "vertices": len(points), "triangles": len(faces), "mode": mode, "authored_joint_indices": influences,
               "missing_joint_indices": missing, "excluded_cardiac": cardiac,
               "display_validation_status": "NOT_VERIFIED"}
        rows.append(row)
        if mode == "unmapped":
            continue
        if not np.allclose(weights.sum(1), 1, rtol=0, atol=1e-6):
            raise ValueError("source weights do not sum to one")
        transforms = deltas[:, joints]
        bound = apply(transforms, points[None, :, None, :])
        positions = np.sum(bound * weights[None, ..., None], axis=2)
        if not np.isfinite(positions).all():
            raise ValueError("nonfinite deformed muscle vertices")
        face_point = faces[:, 0]
        def ref(base):
            vectors = np.einsum("fvkij,vj->fvki", transforms[:, face_point, :, :3, :3], base)
            return np.sum(vectors * weights[None, face_point, :, None], axis=2)
        qa[name] = metrics(points, positions, ref, faces)
        if floor_z is not None and name in ("Right extensor indicis [FJ1493]", "Left extensor indicis [FJ1493M]"):
            depth = float(floor_z - positions[..., 1].min())
            if depth > 1e-6:
                row.update(mode="excluded_floor_crossing", max_depth_below_floor_m=depth)
                continue
        n, _ = clip.mesh(name, "MUSCLES", points, faces, mats[color], weights, joints,
                         source_node=source_node, **source_identity(name, bp))
        row["node"] = n
        check = np.unique(np.linspace(0, len(points) - 1, 5, dtype=int))
        samples_record(name, n, positions[:, check], sample, check)
        if name in ("Clavicular part of right pectoralis major [FJ1447]",
                    "Abdominal part of left pectoralis major [FJ1446M]"):
            # Keep the authored influence support and test bounded weight sharpening.
            sharper = weights ** 2
            sharper /= sharper.sum(1, keepdims=True)
            alternative = np.sum(bound * sharper[None, ..., None], axis=2)
            delta = np.linalg.norm(alternative - positions, axis=-1)
            variant[name] = {"sharpened": metrics(points, alternative, ref, faces),
                             "shift_from_authored_rms_m": np.sqrt((delta ** 2).mean(1)).tolist(),
                             "shift_from_authored_max_m": delta.max(1).tolist()}
            if "right" in name:
                morph_probe(times, indices, points, positions, alternative, faces, folder)
    return rows, qa, variant, perf_counter() - start


def morph_probe(times, indices, points, positions, alternative, faces, folder):
    # Discrete experiment: exact same deformed geometry as the selected LBS surface.
    for name, geometry_rows in (("baked", positions[indices]), ("sharpened", alternative[indices])):
        candidate = Clip(times[indices])
        mat = candidate.material("Pectoralis", [.5, .11, .09])
        node, primitive = candidate.mesh("FJ1447", "MUSCLES", geometry_rows[0], faces, mat)
        primitive["targets"] = [
            {"POSITION": candidate.accessor(p - geometry_rows[0], "VEC3", bounds=True, target=34962)}
            for p in geometry_rows[1:]
        ]
        count = len(geometry_rows)
        candidate.channel(node, "weights", np.eye(count, dtype=float)[:, 1:].ravel(), "SCALAR")
        candidate.finish(folder / (name + "-probe.glb"))
        write(folder / (name + "-probe.json"), {"times_s": times[indices].tolist(),
              "vertex_indices": [0, len(points) // 2, len(points) - 1],
              "world_glb_m": geometry_rows[:, [0, len(points) // 2, len(points) - 1]].tolist()})


def main(args):
    import myo_sim

    started = perf_counter()
    folder = args.output
    folder.mkdir()
    verify(args.myo_glb)
    code = Path(myo_sim.__file__).parent
    fingerprint = hashlib.sha256()
    for f in sorted(x for x in code.rglob("*") if x.is_file() and "__pycache__" not in x.parts):
        fingerprint.update(f.relative_to(code).as_posix().encode() + b"\0" + bytes.fromhex(digest(f)))
    if fingerprint.hexdigest() != MYOSIM_TREE or digest(args.atlas / "catalog.json") != CATALOG_SHA:
        raise ValueError("MyoSim or BodyParts3D catalog pin changed")
    for file, expected in {
        "BodyParts3D-LICENSE": "f4fe9670e99172cd529403fbfb83d6172b2b677daa2ff54bab908888217ab611",
        "source-receipt.json": "727089d6f017e82f32130b833fb9f546c00569507f350ba6ccaa54994e9a6261",
    }.items():
        if not (args.atlas / file).is_file() or digest(args.atlas / file) != expected:
            raise ValueError("BodyParts3D license or provisioning receipt unavailable or changed")
    catalog = json.loads((args.atlas / "catalog.json").read_text())
    bp = {item["fj_id"]: item for item in catalog["meshes"]}
    for fj in TRIAL_BONES:
        obj = bp[fj]
        verify_asset(args.atlas / "meshes" / obj["filename"], obj)
    manifest_path = args.run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if digest(manifest_path) != args.manifest_sha:
        raise ValueError("run manifest revision differs")
    for name in ("trajectory.npz", "summary.json", "series.csv", "model_recipe.json", "validation.json"):
        if digest(args.run / name) != manifest["artifacts"][name]["sha256"]:
            raise ValueError("source run artifact changed: " + name)
    run, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(args.run)
    if run["status"] != "computed" or run["scenario_id"] not in {"pushup", "pushup_palms", "pushup_palms_contact", "pushup_flat_palm"}:
        raise ValueError("a computed push-up run is required")
    control = run["execution"]["parameters"]["control"]
    if run["scientific"]["acceptance"]["muscle_driven"] == "PASS" or control != "assisted_muscle":
        raise ValueError("This binding is pinned to the assisted palm run")
    key_indices = json.loads((args.run / "summary.json").read_text())["key_indices"]
    if key_indices[1] in (key_indices[0], key_indices[2]):
        key_indices[1] = int(np.argmin(abs(times - 2.2)))
        phase_names = ("start", "target bottom", "return time")
    else:
        phase_names = ("start", "bottom", "return")
    phases = dict(zip(key_indices, phase_names, strict=True))
    selected = np.unique([0, len(times) // 4, *phases, len(times) * 3 // 4, len(times) - 1])
    rectus = rectus_register(args.rectus, run["model"])
    neutral = mj.MjData(model)
    mj.mj_forward(model, neutral)
    bones = visible_geoms(model)
    pads = [g for g in range(model.ngeom) if re.fullmatch(r"(palm|toe)_[rl](?:_[12])?", model.geom(g).name)]
    contact = "contact_manifest.json" in run["artifacts"]
    layers = dict(LAYERS)
    if contact:
        for name in ("contact_manifest.json", "contact_surfaces.json"):
            if digest(args.run / name) != run["artifacts"][name]["sha256"]:
                raise ValueError("contact artifact changed: " + name)
        manifest = json.loads((args.run / "contact_manifest.json").read_text())
        surface_frames = json.loads((args.run / "contact_surfaces.json").read_text())["frames"]
        pads = [row["geom_id"] for row in manifest["collision_geoms"].values()]
        layers["OVERLAYS"] = {"mode": "registered_rigid", "available": True,
                             "description": "Floor-only proxy envelopes, native normals and visible depth markers"}
        debug_events = []
    geoms = bones + pads
    raw_glb = args.myo_glb.read_bytes()
    doc, blob = unpack(raw_glb)
    inv, bind, correspondence, matches = joint_matches(doc, blob, model, bones)
    poses = {g: [] for g in geoms}
    rectus_poses, rectus_qa = {"r": [], "l": []}, []
    frames = []
    for i, time_s in enumerate(times):
        restore_state(model, data, states[i], spec, qpos[i], time_s)
        if contact:
            debug_events.append(floor_events(model, data))
        for g in geoms:
            poses[g].append(geom_pose(data, g))
        _, checks, sites = rectus_skin(model, data, rectus)
        rectus_qa.append(checks)
        left = np.subtract(sites["l"][1], sites["r"][1])
        for side, (_, rest, _, _) in rectus.items():
            lo, hi = np.asarray(sites[side])
            rotation, length = segment_frame(lo, hi, left)
            rectus_poses[side].append(matrix(rotation * [1, 1, length / rest], lo))
        frames.append({"state_index": i, "frame_time": float(time_s), "state_sha256": sha(states[i].tobytes()),
                       "phase": phases.get(i, "motion")})
        if contact:
            saved = surface_frames[i]
            if saved["state_sha256"] != frames[-1]["state_sha256"] or saved["time_s"] != float(time_s):
                raise ValueError("contact samples and saved state differ")
            frames[-1]["floor_contact_count"] = len(debug_events[-1])
            frames[-1]["min_surface_distance_m"] = {
                limb: min((dist for name, (dist, _) in saved["surfaces"].items()
                           if manifest["visible_surfaces"][name]["body"].startswith(bodies)), default=None)
                for limb, bodies in {"right hand": ("hand_r",), "left hand": ("hand_l",),
                    "right foot": ("toes_r", "calcn_r"), "left foot": ("toes_l", "calcn_l")}.items()}
    poses = {g: np.array(values) for g, values in poses.items()}
    clip = Clip(times)
    mats = {name: clip.material(name.title(), color) for name, color in {
        "bone": (.67, .60, .47), "muscle": (.41, .068, .059), "chest": (.51, .10, .081),
        "tendon": (.68, .49, .34), "floor": (.045, .063, .080), "pad": (.04, .38, .43)}.items()}
    rig = clip.node("MyoSuite authored skin", children=[])
    joints = []
    deltas = np.repeat(np.eye(4)[None, None], len(times) * len(bind), axis=0).reshape(len(times), len(bind), 4, 4)
    for i, m in enumerate(bind):
        # Imported bind translations and rotations must agree with the inverse bind matrices.
        node = clip.node(f"joint_{i:02d}_" + correspondence[i]["label"], root=False, matrix=m.T.ravel().tolist())
        joints.append(node)
        if i in matches:
            g, source_inverse = matches[i]
            deltas[:, i] = B4 @ poses[g] @ source_inverse @ B4.T
            # Blender and Three require TRS rest fields when a node has TRS animation.
            fields = clip.doc["nodes"][node]
            fields.pop("matrix")
            q = np.empty(4)
            mj.mju_mat2Quat(q, np.ascontiguousarray(m[:3, :3].ravel()))
            fields.update(rotation=q[[1, 2, 3, 0]].tolist(), translation=m[:3, 3].tolist())
            clip.transforms(node, deltas[:, i] @ m)
    clip.doc["nodes"][rig]["children"] = joints
    clip.doc["skins"] = [{"name": "MyoSuite LBS", "joints": joints, "skeleton": rig,
                          "inverseBindMatrices": clip.accessor(inv.transpose(0, 2, 1).reshape(-1, 16), "MAT4")}]
    detailed_hands = {model.geom(g).name for g in bones if model.geom(g).name.startswith("hand_detail_")}
    sample, native, pad_records = [], [], []
    for g in bones:
        mesh = model.geom_dataid[g]
        body = model.body(model.geom_bodyid[g]).name
        name = model.geom(g).name or f"geom{g}_{model.mesh(mesh).name}"
        points, faces = geometry(model, mesh)
        faces = clean_faces(points, faces)
        if not len(faces):
            continue
        n, _ = clip.mesh(name, "SKELETON", points @ BASIS.T, faces, mats["bone"], body=body, geom=g)
        clip.transforms(n, B4 @ poses[g] @ B4.T)
        native.append({"name": name, "node": n, "geom_id": g, "body": body,
                       "mesh": model.mesh(mesh).name, "mode": "registered_rigid",
                       "geom_relative_to_body_m": (np.linalg.inv(matrix(neutral.xmat[model.geom_bodyid[g]],
                                                          neutral.xpos[model.geom_bodyid[g]]))
                                      @ geom_pose(neutral, g)).tolist(),
                       "source_mesh_sha256": sha(points.tobytes() + faces.tobytes())})
        check = np.unique(np.linspace(0, len(points) - 1, 5, dtype=int))
        samples_record(name, n, apply(poses[g][:, None], points[check]) @ BASIS.T, sample, check)
    floor = model.geom("floor").id
    if contact:
        extent_x, extent_y = model.geom_size[floor, :2]
        local = np.array([[-extent_x, -extent_y, 0], [extent_x, -extent_y, 0],
                          [extent_x, extent_y, 0], [-extent_x, extent_y, 0]])
        floor_points = apply(geom_pose(neutral, floor), local) @ BASIS.T
    else:
        floor_points = [[-2, 0, -2], [-2, 0, 2], [3, 0, 2], [3, 0, -2]]
    clip.mesh("World floor", "BODY", floor_points, np.array([[0, 1, 2], [0, 2, 3]]), mats["floor"])
    # The unit sphere is a display of the actual model pad centre and radius.
    points = np.array([[np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)]
                       for t in np.linspace(0, np.pi, 9) for p in np.arange(16) * np.pi / 8])
    faces = np.array([face for row in range(8) for col in range(16)
                      for a, b in [(16 * row + col, 16 * row + (col + 1) % 16)]
                      for face in ((a, a + 16, b), (b, a + 16, b + 16))])
    faces = clean_faces(points, faces)
    if contact:
        experimental_overlays(clip, model, poses, pads, manifest, surface_frames, debug_events, points, faces)
    for g in ([] if contact else pads):
        name = model.geom(g).name
        radius = float(model.geom_size[g, 0])
        node, _ = clip.mesh(name, "OVERLAYS", points * radius, faces, mats["pad"], proxy="native_sphere")
        clip.transforms(node, B4 @ poses[g] @ B4.T)
        pad_records.append({"name": name, "node": node, "geom_id": g, "radius_m": radius,
                            "centres_m": poses[g][:, :3, 3].tolist()})
    floor_z = manifest["floor"]["position_m"][2] if contact and manifest["profile"] == "articulated_palms_v1" else None
    muscles, qa, variants, skin_time = muscle_meshes(clip, doc, blob, bp, matches, deltas, mats,
                                                  sample, times, selected, folder, floor_z)
    z_rows = []
    for side, (points, length, faces, tendon) in rectus.items():
        label = f"Rectus abdominis muscle.{side}"
        positions = B4 @ np.asarray(rectus_poses[side])
        n, primitive = clip.mesh(label, "MUSCLES", points, faces[tendon == 0], mats["chest"], source="Z-Anatomy")
        clip.doc["meshes"][-1]["primitives"].append({**primitive, "material": mats["tendon"],
                                                    "indices": clip.accessor(faces[tendon == 1], "SCALAR", 5123,
                                                                             target=34963)})
        clip.transforms(n, positions)
        z_rows.append({"name": label, "node": n, "vertices": len(points), "triangles": len(faces),
                       "source_mesh_sha256": sha(points.tobytes() + faces.tobytes() + tendon.tobytes()),
                       "mode": "segment_follow_illustrative", "side": side,
                       "rest_landmark_length_m": length, "target_sites": [f"rect_abd_{side}-P{i}" for i in (1, 4)],
                       "display_validation_status": "NOT_VERIFIED"})
    trial = bones_probe(args, model, neutral, bp, poses, times, selected, folder)
    path = folder / "motion.glb"
    clip.finish(path)
    clip_sha = digest(path)
    rotor = {str(g): poses[g].tolist() for g in geoms}
    # Keyframe identity also commits to all native display geometries before float32 quantization.
    for i, f in enumerate(frames):
        packed = np.asarray([poses[g][i] for g in geoms], dtype="<f8")
        f["native_transform_sha256"] = sha(packed.tobytes())
    scene = {
        "schema_version": "hmm.anatomy.motion/1", "run_id": run["run_id"], "scenario_id": run["scenario_id"],
        "source_manifest_sha256": args.manifest_sha, "trajectory_sha256": run["artifacts"]["trajectory.npz"]["sha256"],
        "catalog_sha256": CATALOG_SHA, "control": control, "engine": run["engine"], "model": run["model"],
        "acceptance": run["scientific"]["acceptance"], "human_validation": "NOT_VALIDATED",
        "anatomy_validation": "NOT_VERIFIED", "interpolation": "GLB LINEAR between exact integration states",
        "coordinates": {"world_to_glb": B4.tolist(), "world": "MuJoCo right-handed Z-up metres, +X headward, +Y left",
                        "glb": "right-handed +Y up metres; X/Z = native X/minus native Y",
                        "blender": "right-handed Z-up metres after built-in glTF basis conversion",
                        "bp3d": "bp3d_native_mm right-handed +X left +Y posterior +Z superior"},
        "assets": {"myosuite": {"sha256": ASSETS["light"][2], "revision": REVISION, "license": "CC-BY-4.0"},
                   "myosim": {"tree_sha256": MYOSIM_TREE, "license": "Apache-2.0"},
                   "bp3d": {"catalog_sha256": CATALOG_SHA, "version": "4.3",
                            "membership": "4.3/4.3i operator-local",
                            "license": "CC-BY-SA-2.1-JP",
                            "license_sha256": digest(args.atlas / "BodyParts3D-LICENSE"),
                            "receipt_sha256": digest(args.atlas / "source-receipt.json")},
                   "z_anatomy": Z_SOURCE},
        "frames": frames, "cameras": CAMERAS, "layers": layers, "default_layers": ["BODY", "SKELETON", "MUSCLES"],
        "default_camera": "side",
        "artifacts": {"motion.glb": {"sha256": clip_sha, "bytes": path.stat().st_size}},
    }
    if contact:
        scene["contact"] = {"profile": manifest["profile"], "floor": manifest["floor"],
                            "manifest_sha256": run["artifacts"]["contact_manifest.json"]["sha256"]}
        scene["excluded_display_surfaces"] = [
            {k: row[k] for k in ("name", "source_node", "source_mesh_sha256", "mode", "max_depth_below_floor_m")}
            for row in muscles if row["mode"] == "excluded_floor_crossing"
        ]
    coverage = {"schema_version": "hmm.anatomy.motion.coverage/1", "run_id": run["run_id"],
                "native_bones": native, "source_surfaces": muscles, "z_anatomy_surfaces": z_rows,
                "contacts": [{k: v for k, v in pad.items() if k != "centres_m"} for pad in pad_records],
                "bind_correspondences": correspondence, "counts": dict(Counter(row["mode"] for row in muscles)),
                "static_disputed_objects": {fj: bp[fj] for fj in ("FJ3028", "FJ6043")},
                "native_detailed_hand_meshes": len(detailed_hands), "layers": layers}
    write(folder / "coverage.json", coverage)
    scene["artifacts"]["coverage.json"] = {"sha256": digest(folder / "coverage.json"),
                                          "bytes": (folder / "coverage.json").stat().st_size}
    write(folder / "motion.json", scene)
    write(folder / "geometry.json", {"matching_tolerance_m": LIMIT, "probe_indices": selected.tolist(),
          "skin_proxies": qa, "rectus_fit": rectus_qa, "bounded_weights": variants, "bp3d": trial,
          "pads": pad_records, "pose_geometry_id_order": geoms})
    write(folder / "samples.json", {"n_frames": len(frames), "points": sample, "geom_pose_world_m": rotor,
                                     "joint_pose_glb_m": (deltas @ bind).tolist()})
    write(folder / "build_performance.json", {"elapsed_s": perf_counter() - started,
                                              "skin_build_and_qa_s": skin_time})
    print(f"{run['run_id']}: {len(times)} states, {len(native)} native bones, {len(matches)} joint matches, "
          f"{coverage['counts']}, {len(z_rows)} rectus surfaces, {path.stat().st_size} GLB bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("run", "myo-glb", "atlas", "rectus", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--manifest-sha", required=True)
    parser.add_argument("--accept-licenses", required=True, choices=["CC-BY-4.0,CC-BY-SA-4.0,CC-BY-SA-2.1-JP"])
    main(parser.parse_args())
