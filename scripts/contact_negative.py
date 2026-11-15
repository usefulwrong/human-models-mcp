"""Bounded unvalidated negative control; execute inside the project Docker runtime."""

import hashlib
import json
import platform
from pathlib import Path
import numpy as np
from human_models_mcp.adapters.contact import initialize
from human_models_mcp.registry import ContactParameters, home
from human_models_mcp import __version__

out = {}
for perturb in (0.0, 0.02, -0.02):
    mj, m, d, pelvis, floor, feet, initial = initialize(
        ContactParameters(render=False, initial_velocity_x_m_per_s=perturb)
    )
    rows = []
    for step in range(601):
        if step:
            mj.mj_step(m, d)
        mj.mj_forward(m, d)
        ground = np.zeros(3)
        nonfoot = []
        for i in range(d.ncon):
            c = d.contact[i]
            if floor not in c.geom:
                continue
            f = np.zeros(6)
            mj.mj_contactForce(m, d, i, f)
            sign = 1 if c.geom[0] == floor else -1
            ground += sign * c.frame.reshape(3, 3).T @ f[:3]
            other = int(c.geom[1] if c.geom[0] == floor else c.geom[0])
            if not m.geom(other).name.startswith(("calcn_skin", "toes_skin")):
                nonfoot.append(m.geom(other).name)
        if step % 50 == 0 or nonfoot or d.warning.number.any():
            rows.append(
                {
                    "time_s": float(d.time),
                    "com_m": d.subtree_com[pelvis].tolist(),
                    "root_origin_m": d.xpos[pelvis].tolist(),
                    "root_qvel": d.qvel[:6].tolist(),
                    "grf_world_N": ground.tolist(),
                    "nonfoot_floor_contacts": nonfoot,
                    "warnings": d.warning.number.tolist(),
                }
            )
        if d.warning.number.any() or nonfoot:
            break
    out[str(perturb)] = {
        "status": "exploratory_negative_control_not_a_balance_acceptance",
        "initial_velocity_x_m_per_s": perturb,
        "initial": initial,
        "observations": rows,
        "final_com_height_change_m": float(d.subtree_com[pelvis, 2] - initial["initial_com_world_m"][2]),
        "no_external_support": not bool(np.any(d.xfrc_applied)),
    }
    print(perturb, out[str(perturb)]["final_com_height_change_m"], rows[-1], flush=True)
lock = json.loads((home() / "models.lock.json").read_text())
provenance = {
    "model_id": "ms_human_700_locomotion",
    "source_url": lock["source_url"],
    "revision": lock["revision"],
    "asset_sha256": lock["asset_sha256"],
    "license": lock["license"],
    "engine": {"name": "mujoco", "version": mj.__version__},
    "package_version": __version__,
    "python": platform.python_version(),
    "execution_method": "dynamic_forward",
    "physics_backend": "cpu",
    "render_backend": "none",
    "seed": None,
    "maximum_duration_s": 1.2,
    "timestep_s": 0.002,
    "solver_tolerance": 1e-12,
    "solver_iterations": 200,
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "units": {
        "com_m": "m",
        "root_origin_m": "m",
        "root_qvel": "first three m/s; last three rad/s, in source joint order",
        "grf_world_N": "N",
    },
    "root_joint_order": [m.joint(i).name for i in range(6)],
    "validation_level": "unvalidated",
    "scope": "Extended uncontrolled diagnostic outside the accepted short contact probe; no balance, fall accuracy or safety certification.",
}
assert all(
    np.isfinite(r["com_m"]).all() and np.isfinite(r["grf_world_N"]).all()
    for run in out.values()
    for r in run["observations"]
)
(home() / "reports/V05_NEGATIVE_BALANCE.json").write_text(
    json.dumps({"provenance": provenance, "experiments": out}, indent=2) + "\n"
)
