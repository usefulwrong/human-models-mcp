"""Export a three-state, local-only Anatomy Lab replay from a verified Blender job."""

import argparse
import hashlib
import json
from pathlib import Path

import mujoco as mj
import numpy as np

from human_models_mcp.atlas import atlas_lock, atlas_lock_digest
from human_models_mcp.atlas_registration import BONES, native_bone, nearest, register, skin, surface
from human_models_mcp.render_worker import source_integrity
from human_models_mcp.rendering import digest, write_json
from human_models_mcp.scene_export import load_saved_run, restore_state


def read(path):
    return json.loads(path.read_text())


def anchor(model, data, name):
    joint = model.joint(name).id
    return {"position_m": data.xanchor[joint].tolist(), "axis": data.xaxis[joint].tolist()}


def native_surface(model, data, name):
    mesh = model.geom(name).dataid[0]
    first, count = model.mesh_faceadr[mesh], model.mesh_facenum[mesh]
    faces = model.mesh_face[first:first + count]
    return {"vertices_m": native_bone(model, data, name).tolist(),
            "faces": faces[np.diff(np.sort(faces, axis=1), axis=1).min(axis=1) > 0].tolist()}


def registration_control(source_mm, native, basis, fit):
    source_m = source_mm @ basis.T / 1000
    translated = source_m + native.mean(0) - source_m.mean(0)
    aligned = source_m @ np.asarray(fit["source_rotation_row_vectors"]) + fit["source_translation_m"]
    return {
        name: {
            "native_to_atlas_rmse_m": float(np.sqrt(np.mean(nearest(native, points)[1] ** 2))),
            "atlas_to_native_rmse_m": float(np.sqrt(np.mean(nearest(points, native)[1] ** 2))),
        }
        for name, points in (("basis_and_centroid", translated), ("v08_trimmed_icp", aligned))
    }


def transform(data, body, rest, basis, fit, source_mm, native):
    rest_rotation, rest_position = rest
    body_delta = data.xmat[body].reshape(3, 3) @ rest_rotation.T
    rotation = body_delta @ np.asarray(fit["source_rotation_row_vectors"]).T @ basis
    translation = data.xpos[body] + body_delta @ (fit["source_translation_m"] - rest_position)
    matrix = np.eye(4)
    matrix[:3, :3] = rotation / 1000
    matrix[:3, 3] = translation
    determinant = float(np.linalg.det(rotation))
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-10, rtol=0) or abs(determinant - 1) > 1e-10:
        raise ValueError("invalid source-to-world proper rotation")
    raw = source_mm @ matrix[:3, :3].T + matrix[:3, 3]
    landmarks = [
        {**item, "residual_m": float(np.linalg.norm(raw[item["atlas_vertex"]] - native[item["native_vertex"]]))}
        for item in fit["landmark_proxies"]
    ]
    if any(abs(a["residual_m"] - b["residual_m"]) > 1e-10
           for a, b in zip(landmarks, fit["landmark_proxies"], strict=True)):
        raise ValueError("rigid landmark residual changed with saved state")
    return {"matrix": matrix.tolist(), "proper_rotation_determinant": determinant,
            "scale_m_per_mm": .001, "landmark_proxies": landmarks}, raw


def triangle_normals(points, faces):
    triangles = points[faces]
    return np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])


def comparison(model, data, registration, unbounded):
    faces, locals_, baseline, _ = registration
    anchors = []
    for vertices, (_, _, body_name, _) in zip(locals_, BONES, strict=True):
        body = model.body(body_name).id
        anchors.append(vertices @ data.xmat[body].reshape(3, 3).T + data.xpos[body])
    first, second = anchors
    normal_a, normal_b = (triangle_normals(vertices, faces) for vertices in anchors)
    results, meshes = {}, {}
    for name, weights in (
        ("rigid_clavicle_control", np.zeros_like(baseline)),
        ("linear_unbounded_two_bone", unbounded),
        ("v08_clipped_two_bone", baseline),
        ("bounded_smooth_two_bone", baseline ** 2 * (3 - 2 * baseline)),
    ):
        points = first + weights * (second - first)
        normals = triangle_normals(points, faces)
        average = weights[faces].mean(axis=1)
        normal_ref = normal_a + average * (normal_b - normal_a)
        z = points[faces, 2]
        gaps = {}
        for (_, _, body_name, site), mask in zip(
            BONES, (baseline[:, 0] <= .05, baseline[:, 0] >= .95), strict=True
        ):
            gaps[body_name] = float(np.linalg.norm(points[mask] - data.site_xpos[model.site(site).id], axis=1).min())
        results[name] = {
            "endpoint_gap_m": gaps,
            "minimum_triangle_area_m2": float(np.linalg.norm(normals, axis=1).min() / 2),
            "fold_inversion_proxy_faces": int(np.count_nonzero(np.sum(normals * normal_ref, axis=1) < 0)),
            "minimum_height_m": float(z.min()),
            "ground_plane_crossing_triangles": int(np.count_nonzero((z.min(1) <= 0) & (z.max(1) >= 0))),
        }
        meshes[name] = points.tolist()
    return results, meshes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path, help="completed local three-frame pushup_anatomy render job")
    parser.add_argument("output", type=Path, help="new directory for replay and geometric QA")
    args = parser.parse_args()
    job, output = args.job, args.output
    record = read(job / "job.json")
    artifacts = job / "artifacts"
    if record["status"] != "completed" or record["request"].get("recipe") != "pushup_anatomy":
        raise ValueError("a completed pushup_anatomy job is required")
    source_integrity(job, record)
    for name in ("scene.blend", "passport.json", "evidence.json", "frames.json", "anatomy_registration.json"):
        if digest(artifacts / name) != record["artifacts"][name]["sha256"]:
            raise ValueError("render artifact hash mismatch: " + name)
    frames_manifest = read(artifacts / "frames.json")
    rendered = read(job / "work/expected.json")
    passport = read(artifacts / "passport.json")
    phase_indices = frames_manifest["phase_source_indices"]
    if len(rendered["frames"]) != 3 or list(phase_indices) != ["start", "bottom", "return"]:
        raise ValueError("expected start, bottom and return in a three-frame render")
    run, model, data, _, _, states, times, qpos, spec, rows = load_saved_run(job / "input")
    if run["scenario_id"] not in {"pushup_flat_palm", "pushup_palms"}:
        raise ValueError("regional replay requires a supported palm push-up run")
    mj.mj_forward(model, data)
    lock = atlas_lock()
    atlas_hash = atlas_lock_digest(lock)
    if atlas_hash != record["request"]["atlas_lock_sha256"]:
        raise ValueError("atlas lock mismatch")
    registration = register(model, data, run["model"], job / "input")
    faces, _, _, registration_report = registration
    basis = np.asarray(lock["source_coordinates"]["world_basis"])
    source = {filename: surface(job / "input" / filename, asset)
              for filename, asset in lock["files"].items()}
    structures = {
        asset["object_id"]: {
            "fma_id": asset["anatomical_id"], "bp_id": asset["representation_id"],
            "label": asset["label"], "patient_side": "right",
            "pose_kind": "illustrative_surface" if filename == "FJ1447.obj" else "registered_rigid",
            "source_sha256": asset["sha256"],
            "vertices_mm": source[filename][0].tolist(), "faces": source[filename][1].tolist(),
        }
        for filename, asset in lock["files"].items()
    }
    bone_fits = registration_report["bone_fits"]
    regions, controls, distances = [], {}, []
    for (filename, geom, body_name, site), fit in zip(BONES, bone_fits, strict=True):
        body = model.body(body_name).id
        if int(model.geom(geom).bodyid[0]) != body or not body_name.endswith("_r"):
            raise ValueError("source-to-native right side mapping mismatch")
        raw, _ = source[filename]
        rest = data.xmat[body].reshape(3, 3).copy(), data.xpos[body].copy()
        object_id = lock["files"][filename]["object_id"]
        controls[object_id] = registration_control(raw, native_bone(model, data, geom), basis, fit)
        regions.append((object_id, geom, body, rest, fit, raw))
        distances.append(nearest(source["FJ1447.obj"][0] @ basis.T / 1000, raw @ basis.T / 1000)[1])
    unbounded = (distances[0] / np.maximum(distances[0] + distances[1], 1e-12))[:, None]
    frames, qa_frames = [], []
    for (phase, index), emitted, blender_frame in zip(
        phase_indices.items(), rendered["frames"], frames_manifest["frames"], strict=True
    ):
        restore_state(model, data, states[index], spec, qpos[index], times[index])
        state_sha = hashlib.sha256(states[index].tobytes()).hexdigest()
        state_clock = index, float(data.time), state_sha
        for frame in (emitted, blender_frame):
            if (frame["source_index"], frame["time_s"], frame["state_sha256"]) != state_clock:
                raise ValueError("render and model state identity differ")
        joint_anchors = {name: anchor(model, data, name) for name in
                         ("sternoclavicular_r2_r", "shoulder_elv_r", "shoulder_elv_l", "elbow_flexion_r")}
        right, left = (np.asarray(joint_anchors[f"shoulder_elv_{side}"]["position_m"]) for side in "rl")
        midpoint = (right + left) / 2
        direction = (right - left) / np.linalg.norm(right - left)
        transforms = {}
        for object_id, geom, body, rest, fit, raw in regions:
            transform_record, vertices = transform(data, body, rest, basis, fit, raw, native_bone(model, data, geom))
            side_distance = float((vertices.mean(0) - midpoint) @ direction)
            if side_distance <= 0:
                raise ValueError("registered bone centroid crosses shoulder laterality plane")
            transform_record["patient_right_centroid_distance_m"] = side_distance
            transforms[object_id] = transform_record
        vertices, skin_checks = skin(model, data, registration)
        if not np.array_equal(vertices, emitted["atlas_vertices_m"]) or not np.array_equal(faces, rendered["atlas"]["faces"]):
            raise ValueError("viewer geometry differs from Blender input surface")
        comparisons, meshes = comparison(model, data, registration, unbounded)
        if not np.array_equal(vertices, meshes["v08_clipped_two_bone"]):
            raise ValueError("the skinning control differs from the replay surface")
        frame_id = {"phase": phase, "state_index": index, "frame_time": state_clock[1], "state_sha256": state_sha}
        frames.append({
            **frame_id, "transforms": transforms, "joint_anchors_m": joint_anchors,
            "surface": {"FJ1447": {"vertices_m": vertices.tolist(), "checks": skin_checks}},
        })
        qa_frames.append({
            **frame_id, "variants": comparisons, "variant_vertices_m": meshes,
            "attachment_sites_m": {site: data.site_xpos[model.site(site).id].tolist()
                                   for _, _, _, site in BONES},
            "native_bones": {name: native_surface(model, data, name) for name in ("clavicle", "humerus", "scapula")},
            "native_path_observations": {key: float(value) for key, value in rows[index].items()
                                         if key.startswith(("pectoralis_", "triceps_", "serratus_", "lumbar_", "abdominal_"))},
        })
    output.mkdir()
    write_json(output / "motion.json", {
        "schema_version": "1.0", "run_id": run["run_id"], "scenario_id": run["scenario_id"],
        "source_sha": record["source_files"]["trajectory.npz"],
        "source_manifest_sha256": record["source_files"]["manifest.json"],
        "atlas_hash": atlas_hash, "atlas": lock, "scene_sha": digest(artifacts / "scene.blend"),
        "renderer_version": passport["renderer"]["blender_version"], "device": passport["renderer"]["device"],
        "camera": passport["renderer"]["camera"], "evidence": {
            "render_evidence_sha256": digest(artifacts / "evidence.json"),
            "scientific_acceptance": run["scientific"]["acceptance"],
            "geometry_transfer": "checked", "anatomical_registration": "illustrative",
            "physics_reintegration": False, "material": "constant display material; activation unmapped",
        },
        "coordinates": {
            "source": lock["source_coordinates"],
            "world": "right-handed MuJoCo/Blender model world, Z up, metres",
            "transform": "row-major 4x4, multiply source millimetre column vector to obtain model world metres",
        },
        "structures": structures, "frames": frames,
    })
    write_json(output / "motion-qa-input.json", {
        "rigid_fit_controls": controls, "registration": registration_report,
        "surface_faces": faces.tolist(), "frames": qa_frames,
    })


if __name__ == "__main__":
    main()
