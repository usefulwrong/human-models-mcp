"""Short uncontrolled full-model integration with one prescribed excitation."""

import csv
import json
from pathlib import Path

from ..registry import ForwardParameters, ForwardValidation
from ..results import error
from .mujoco import load, render


def forward(params: dict, output: Path, validation: dict) -> dict:
    import numpy as np

    p = ForwardParameters.model_validate(params)
    ForwardValidation.model_validate(validation)
    mj, m, d = load()
    aid = mj.mj_name2id(m, mj.mjtObj.mjOBJ_ACTUATOR, p.muscle)
    if aid < 0:
        return error("unsupported", "muscle absent from this model")
    activation_id = int(m.actuator_actadr[aid])
    if activation_id < 0 or m.actuator_dyntype[aid] != mj.mjtDyn.mjDYN_MUSCLE:
        return error("unsupported", "requires a muscle-dynamics actuator")
    d.qvel[:] = 0
    d.act[:] = 0
    d.ctrl[:] = 0
    d.ctrl[aid] = p.excitation
    rows, poses = [], []
    for step in range(p.steps + 1):
        if step:
            mj.mj_step(m, d)
        mj.mj_forward(m, d)
        if not all(np.isfinite(x).all() for x in (d.qpos, d.qvel, d.act, d.actuator_force)):
            raise ValueError("non-finite engine state")
        if d.warning.number.any():
            raise ValueError(f"engine emitted warnings: {d.warning.number.tolist()}")
        activation = float(d.act[activation_id])
        if not 0 <= activation <= 1:
            raise ValueError("muscle activation outside [0, 1]")
        rows.append({"sample": step, "time_s": float(d.time), "excitation": p.excitation,
                     "activation": activation, "length_m": float(d.actuator_length[aid]),
                     "actuator_force_N": float(d.actuator_force[aid])})
        poses.append(d.qpos.tolist())
    elapsed = float(d.time)
    if abs(elapsed - p.steps * m.opt.timestep) > 1e-12:
        raise ValueError("engine elapsed time differs from integrated step count")
    with (output / "series.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metrics = [{"name": "elapsed_time", "value": elapsed, "unit": "s"},
               {"name": "final_activation", "value": rows[-1]["activation"], "unit": "1"},
               {"name": "final_actuator_force", "value": rows[-1]["actuator_force_N"], "unit": "N",
                "definition": "Signed MuJoCo actuator_force; negative denotes pulling along the muscle transmission."},
               {"name": "final_length", "value": rows[-1]["length_m"], "unit": "m"}]
    (output / "summary.json").write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2))
    (output / "poses.json").write_text(json.dumps({"model_id": "ms_human_700", "muscle": p.muscle,
        "method": "dynamic_forward", "simulation_time_s": elapsed, "integration_steps": p.steps,
        "timestep_s": m.opt.timestep, "time_s": [r["time_s"] for r in rows], "qpos": poses,
        "joint_order": [m.joint(i).name for i in range(m.njnt)]}, indent=2))
    render_info = {"status": "not_requested", "render_backend": "none"}
    if p.render:
        try:
            render_info = render(mj, m, d, output, poses[-1], p.steps, "dynamic_forward", p.steps)
        except Exception as exc:
            render_info = {"status": "failed", "render_backend": "none", "message": str(exc)[:500]}
    return {"status": "computed", "metrics": metrics, "render": render_info,
            "checks": [{"name": name, "status": "pass"} for name in
                       ("finite_state", "zero_engine_warnings", "activation_bounds", "elapsed_time")],
            "integration_steps": p.steps, "simulation_time_s": elapsed,
            "integrator": mj.mjtIntegrator(int(m.opt.integrator)).name,
            "initial_conditions": {"keyframe": "init", "qvel": "zero", "activation": "zero",
                                   "other_excitations": 0, "gravity_m_per_s2": m.opt.gravity.tolist(), "scene_floor": False},
            "counts": {"nq": m.nq, "nv": m.nv, "actuators": m.nu, "tendons": m.ntendon},
            "timestep_s": m.opt.timestep,
            "time_series": {"artifact_id": "series.csv", "axis": "time_s", "units":
                {"sample": "1", "time_s": "s", "excitation": "1", "activation": "1", "length_m": "m", "actuator_force_N": "N"},
                "definition": "Uncontrolled mj_step integration from upstream init under gravity; one constant excitation, all others zero."}}
