"""Read the saved pilot routes and compare named bone surfaces across source frames."""

import argparse
import json
from pathlib import Path

import mujoco as mj
import numpy as np

from anatomy_lab import digest
from build import BASIS, apply, geom_pose
from human_models_mcp.atlas import atlas_lock, verify_asset
from human_models_mcp.atlas_registration import native_bone, nearest, rigid_fit
from human_models_mcp.scene_export import load_saved_run, restore_state

BONES = {"Sternum": "sternum", "r_foot": "right calcaneus", "l_foot": "left calcaneus"}
for side, suffix in (("right", "r"), ("left", "l")):
    mirrored = "_mirror" if suffix == "l" else ""
    BONES.update({name + mirrored: f"{side} {name}" for name in ("clavicle", "scapula", "humerus")})
    BONES.update({f"{suffix}_{name}": f"{side} {name}" for name in ("tibia", "fibula")})
PILOTS = {228: "PECM3_l", 229: "PECM3_r", 237: "PECM1_l", 239: "PECM1_r", 495: "PECM2_l", 496: "PECM2_r",
          351: "SUBSC_l", 460: "SUBSC_r", 348: "soleus_l", 457: "soleus_r", 290: None, 402: None}
ANCHORS = (0, 27, 55, 83, 110)


def bone_fit(model, neutral, catalog, install):
    basis = np.asarray(atlas_lock()["source_coordinates"]["world_basis"])
    if not np.allclose(basis @ basis.T, np.eye(3)) or not np.isclose(np.linalg.det(basis), 1):
        raise ValueError("invalid BodyParts3D basis conversion")
    result = {}
    for native, label in BONES.items():
        options = [row for row in catalog["meshes"] if row["label"].lower() == label.lower()
                   and row["identity_status"] == "MATCH" and row["side"] == (
                       label.split()[0] if " " in label else "unknown")]
        if not options or native.endswith("_foot"):
            result[native] = {"catalog_label": label, "status": "NOT_VERIFIED", "candidates": [
                {"fj_id": x["fj_id"], "sha256": x["sha256"]} for x in options],
                "reason": "COMPOSITE_NATIVE_FOOT" if native.endswith("_foot") else "NO_EQUIVALENT_OBJECT"}
            continue
        result[native] = {"status": "GEOMETRIC_MEASUREMENT", "catalog_label": label,
                          "alternatives": [fit_pair(model, neutral, native, row, install, basis) for row in options]}
    return result


def fit_pair(model, neutral, native, row, install, basis):
    path = install / "meshes" / row["filename"]
    verify_asset(path, row)
    vertices = np.asarray([[float(x) for x in line.split()[1:4]]
                           for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("v ")])
    s = vertices[np.linspace(0, len(vertices)-1, min(1200, len(vertices)), dtype=int)] @ basis.T / 1000
    points = native_bone(model, neutral, native)
    t = points[np.linspace(0, len(points)-1, min(1200, len(points)), dtype=int)]
    rotation, offset = np.eye(3), t.mean(0) - s.mean(0)
    before = s + offset
    for _ in range(25):
        paired, d = nearest(t, s @ rotation + offset)
        keep = d <= np.quantile(d, .9)
        rotation, offset = rigid_fit(s[paired[keep]], t[keep])
    after = s @ rotation + offset
    geom = model.geom(native).id
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation.T @ basis / 1000, offset
    local = np.linalg.inv(geom_pose(neutral, geom)) @ transform
    if not np.allclose(apply(geom_pose(neutral, geom) @ local, vertices[:3]), vertices[:3] @ transform[:3, :3].T + offset):
        raise ValueError("nonreproducible basis composition")
    return {"fj_id": row["fj_id"],
                      "source_sha256": row["sha256"], "geom_id": geom, "side": row["side"],
                      "body": model.body(model.geom_bodyid[geom]).name, "source_mm_to_native_geom_m": local.tolist(),
                      "rotation_det": float(np.linalg.det(rotation)), "sample_counts": [len(s), len(t)],
                      "atlas_to_native_before_rms_m": float(np.sqrt(np.mean(nearest(t, before)[1]**2))),
                      "atlas_to_native_after_rms_m": float(np.sqrt(np.mean(nearest(t, after)[1]**2))),
                      "native_to_atlas_after_rms_m": float(np.sqrt(np.mean(nearest(after, t)[1]**2))),
                      "independent_landmarks": "NOT_VERIFIED"}


def measure(args):
    raw = args.crosswalk.read_bytes()
    mapping = json.loads(raw)
    catalog_raw = args.catalog.read_bytes()
    motion_raw = (args.clip / "motion.json").read_bytes()
    manifest_raw = (args.run / "manifest.json").read_bytes()
    if (digest(catalog_raw) != mapping["anatomy_revision"] or digest(motion_raw) != mapping["motion_sha256"]
            or digest(manifest_raw) != mapping["source_result_sha256"] or digest(raw) != args.crosswalk_sha256):
        raise ValueError("registration inputs differ from the pinned scene")
    manifest = json.loads(manifest_raw)
    for file in ("model_recipe.json", "trajectory.npz", *manifest["outputs"]["muscles"]["chunks"]):
        if digest((args.run / file).read_bytes()) != manifest["artifacts"][file]["sha256"]:
            raise ValueError(f"original run artifact differs: {file}")
    run, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(args.run)
    motion = json.loads(motion_raw)
    coverage_raw = (args.clip / "coverage.json").read_bytes()
    if digest(coverage_raw) != motion["artifacts"]["coverage.json"]["sha256"] or len(times) != 111:
        raise ValueError("wrong coverage or saved clock")
    coverage = json.loads(coverage_raw)
    rows = {r["exact_name"]: r for r in mapping["rows"]}
    names = {x for x in PILOTS.values() if x} | {"EO_R5_r", "EO_R5_l"}
    routes = {name: {"native_id": rows[name]["id"], "tendon_id": rows[name]["tendon_id"],
                     "links": rows[name]["links"], "samples": []} for name in sorted(names)}
    lengths = []
    for filename in run["outputs"]["muscles"]["chunks"]:
        with np.load(args.run / filename, allow_pickle=False) as chunk:
            lengths.extend(chunk["length_m"])
    for i, (state, tick) in enumerate(zip(states, times, strict=True)):
        frame = motion["frames"][i]
        if digest(state.tobytes()) != frame["state_sha256"] or tick != frame["frame_time"]:
            raise ValueError("state differs from MotionScene")
        restore_state(model, data, state, spec, qpos[i], tick)
        for name, route in routes.items():
            sites = [a["object_id"] for a in route["links"] if a["kind"] == "site"]
            bodies = model.site_bodyid[np.array([sites[0], sites[-1]])]
            tendon, aid = route["tendon_id"], route["native_id"]
            adr, n = data.ten_wrapadr[tendon], data.ten_wrapnum[tendon]
            wrap = data.wrap_xpos.reshape(-1, 3)[adr:adr+n]
            native_length = float(data.actuator_length[aid])
            if not np.isclose(native_length, lengths[i][aid], atol=1e-10, rtol=0):
                raise ValueError(f"recorded length differs for {name} at {i}")
            sites_pos = data.site_xpos[sites]
            route["samples"].append({"state_index": i, "time_s": float(tick),
                                     "model_sites_world_m": sites_pos.tolist(),
                                     "endpoint_rotation_world": data.xmat[bodies].reshape(2, 3, 3).tolist(),
                                     "native_length_m": native_length, "wrap_polyline_world_m": wrap.tolist(),
                                     "wrap_object_id": data.wrap_obj.reshape(-1)[adr:adr+n].tolist(),
                                     "site_chord_lengths_m": np.linalg.norm(np.diff(sites_pos, axis=0), axis=1).tolist()})
    neutral = mj.MjData(model)
    mj.mj_forward(model, neutral)
    assets = mapping["reviewed_display_assets"]
    for node, name in PILOTS.items():
        if name is None or name.startswith("PECM3"):
            assert not assets.get(str(node), {}).get("part_actuator_id")
        else:
            assert assets[str(node)]["part_actuator_id"] == rows[name]["id"]
    result = {"run_id": run["run_id"], "motion_sha256": digest(motion_raw), "crosswalk_revision": 3,
              "mapping_revision_sha256": args.crosswalk_sha256, "anchors": ANCHORS, "clock_s": times.tolist(),
              "frame_basis": {"native_to_gltf": BASIS.tolist(), "native": "right-handed metres, Z up",
                              "bodyparts3d_to_native_basis": atlas_lock()["source_coordinates"],
                              "bone_fit_rest_pose": "MuJoCo qpos0",
                              "motion_rest_anchor": "first exact saved state, separate from qpos0"},
              "pilot_surfaces": {node: {"route_control": name, **mapping["motion_display_assets"][str(node)]}
                                 for node, name in PILOTS.items()},
              "routes": routes, "bone_fits": bone_fit(model, neutral, json.loads(catalog_raw), args.catalog.parent),
              "native_bones": coverage["native_bones"], "myosuite_bind": coverage["bind_correspondences"],
              "limitations": ["No independent landmarks or attachment footprints were paired.",
                              "The model calcn body holds a composite foot mesh. No isolated calcaneus transfer asserted.",
                              "The model tibia body holds distinct tibia and fibula meshes.",
                              "PECM3 is a sided-group control, and EO_R5 is a native-only candidate."],
              "anatomical_registration": "NOT_VERIFIED"}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(routes)} native routes x {len(times)} saved states, {len(result['bone_fits'])} named bone controls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("run", "catalog", "crosswalk", "clip", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    parser.add_argument("--crosswalk-sha256", required=True)
    measure(parser.parse_args())
