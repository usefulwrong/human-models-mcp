"""Audit saved push-up states against the physical plane in metres."""

import argparse
import hashlib
from pathlib import Path

import numpy as np

TARGET_M = 0.002
HARD_LIMIT_M = 0.005


def triangle_metrics(distance, faces):
    triangles = distance[faces]
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    depth = np.maximum(0, -low)
    return {
        "min_signed_m": float(distance.min()),
        "max_depth_m": float(depth.max()),
        "p95_triangle_depth_m": float(np.quantile(depth, .95)),
        "triangles_crossing": int(np.count_nonzero((low < 0) & (high > 0))),
        "triangles_below": int(np.count_nonzero(high < 0)),
        "triangles_over_target": int(np.count_nonzero(depth > TARGET_M)),
        "triangles_over_hard_limit": int(np.count_nonzero(depth > HARD_LIMIT_M)),
    }


def audit(source, output):
    import mujoco as mj

    from human_models_mcp.adapters.contact import dump, measure_contacts, momentum_rates
    from human_models_mcp.scene_export import load_saved_run, restore_state

    run, m, d, _, recipe, states, times, qpos, spec, _ = load_saved_run(source)
    manifest_hash = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    identity = {"run_id": run["run_id"], "manifest_sha256": manifest_hash, "recipe": recipe}
    artifacts = ["trajectory.npz", "palm_reference_input.json", "model_recipe.json"]
    artifacts += sorted(p.name for p in source.glob("muscles_*.npz"))
    identity["verified_input_sha256"] = {}
    for name in artifacts:
        digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
        if run["artifacts"][name]["sha256"] != digest:
            raise ValueError(f"run artifact hash differs: {name}")
        identity["verified_input_sha256"][name] = digest

    floor = m.geom("floor").id
    visible = {}
    geoms = []
    for g in range(m.ngeom):
        name = m.geom(g).name
        body = m.body(m.geom_bodyid[g]).name
        masks = int(m.geom_contype[g]), int(m.geom_conaffinity[g])
        eligible = bool((masks[0] & m.geom_conaffinity[floor]) or (masks[1] & m.geom_contype[floor]))
        geoms.append({"id": g, "name": name, "body": body, "contype": masks[0],
                      "conaffinity": masks[1], "floor_mask_eligible": eligible and g != floor})
        if m.geom_type[g] != mj.mjtGeom.mjGEOM_MESH or m.geom_rgba[g, 3] <= 0:
            continue
        mesh = m.geom_dataid[g]
        v, f = m.mesh_vertadr[mesh], m.mesh_faceadr[mesh]
        visible[g] = (m.mesh_vert[v:v + m.mesh_vertnum[mesh]].astype(float),
                      m.mesh_face[f:f + m.mesh_facenum[mesh]])

    visual, mechanical = [], []
    scratch = mj.MjData(m)
    pelvis = m.body("pelvis").id
    for i, t in enumerate(times):
        restore_state(m, d, states[i], spec, qpos[i], t)
        guides = []
        if recipe.get("support_boundary") == "fixed_points":
            from human_models_mcp.adapters.supports import fixed_reactions, measure_fixed_supports

            guides = fixed_reactions(mj, m, d)
            force, moment, contacts, support, friction_error = measure_fixed_supports(mj, m, d, i, recipe["friction"])
        else:
            force, moment, contacts, support, friction_error = measure_contacts(mj, m, d, floor, i, ("palm_", "toe_", "guard_"))
        acceleration, hdot, _ = momentum_rates(mj, m, d, scratch, pelvis, 1e-6)
        mass = m.body_subtreemass[pelvis]
        state_hash = hashlib.sha256(states[i].astype("<f8").tobytes()).hexdigest()
        frame = {"index": i, "time_s": float(t), "state_sha256": state_hash}
        mechanical.append({**frame, "contacts": contacts, "guides": guides, "support": support,
                           "ground_force_N": force.tolist(), "net_moment_about_com_Nm": moment.tolist(),
                           "force_balance_error_N": float(np.linalg.norm(mass * (acceleration - m.opt.gravity) - force)),
                           "moment_balance_error_Nm": float(np.linalg.norm(hdot - moment)),
                           "friction_error_N": friction_error, "warnings": d.warning.number.tolist()})
        for progress in (0., .25, .5, .75) if i + 1 < len(times) else (0.,):
            if progress:
                d.qpos[:] = (1 - progress) * qpos[i] + progress * qpos[i + 1]
                mj.mj_kinematics(m, d)
            origin = d.geom_xpos[floor]
            normal = d.geom_xmat[floor].reshape(3, 3)[:, 2]
            surfaces = {}
            for g, (points, faces) in visible.items():
                r = d.geom_xmat[g].reshape(3, 3)
                distance = points @ (r.T @ normal) + (d.geom_xpos[g] - origin) @ normal
                surfaces[str(g)] = triangle_metrics(distance, faces)
            visual.append({**frame, "fraction_to_next": progress, "sample_time_s": float(t + progress * (times[min(i+1, len(times)-1)] - t)),
                           "floor_origin_m": origin.tolist(), "floor_normal": normal.tolist(), "surfaces": surfaces})
    output.mkdir(parents=True, exist_ok=True)
    dump(output / "CONTACT_AUDIT.json", {**identity, "geometries": geoms, "frames": mechanical,
                                         "floor_geom_id": floor, "equalities": [int(t) for t in m.eq_type]})
    dump(output / "VISUAL_PENETRATION.json", {**identity, "target_m": TARGET_M, "hard_limit_m": HARD_LIMIT_M,
         "interpolation": "quarter points of coordinate-linear diagnostic; viewer SKIN/TRS paths separately audited",
         "geometry": [geoms[g] for g in visible], "frames": visual})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.run, args.output)
