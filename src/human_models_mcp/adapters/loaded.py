"""Full musculoskeletal model with an explicit soft pelvis fixture and joint load."""

import csv
import hashlib
import json
from pathlib import Path

from ..registry import LoadedParameters, TrackingParameters, ForwardValidation, home


def reference_motion(time_s: float, target_rad: float):
    u = min(time_s / .3, 1.0)
    return (target_rad * (10*u**3 - 15*u**4 + 6*u**5),
            target_rad / .3 * (30*u**2 - 60*u**3 + 30*u**4) if u < 1 else 0.0)


def controller_torque(time_s: float, angle: float, velocity: float, target_rad: float):
    target, speed = reference_motion(time_s, target_rad)
    return max(-8.0, min(8.0, 40 * (target-angle) + 3 * (speed-velocity)))


def fixture_model(timestep_s: float):
    import mujoco as mj
    spec = mj.MjSpec.from_file(str(home() / "models/ms_human_700/MS-Human-700.xml"))
    spec.option.timestep = timestep_s
    base = spec.compile()
    initial = mj.MjData(base)
    mj.mj_resetDataKeyframe(base, initial, 0)
    mj.mj_forward(base, initial)
    fixture = spec.add_equality(name="fixture_pelvis", type=mj.mjtEq.mjEQ_WELD,
                      objtype=mj.mjtObj.mjOBJ_BODY, name1="pelvis", name2="world")
    fixture.data[:3] = initial.xpos[base.body("pelvis").id]
    fixture.solref[:] = [.02, 1]
    fixture.solimp[:] = [.95, .95, .001, .5, 2]
    model = spec.compile()
    data = mj.MjData(model)
    mj.mj_resetDataKeyframe(model, data, 0)
    mj.mj_forward(model, data)
    return mj, model, data, spec.to_xml()


def loaded_elbow(params: dict, output: Path, validation: dict, *, tracking: bool = False) -> dict:
    import numpy as np
    p = (TrackingParameters if tracking else LoadedParameters).model_validate(params)
    ForwardValidation.model_validate(validation)
    mj, m, d, xml = fixture_model(p.timestep_s)
    (output / "derived_model.xml").write_text(xml)
    derivation = {"source_variant": "primary", "fixture": "soft pelvis-to-world weld anchored at initial pelvis origin",
                  "added_equality": "fixture_pelvis", "added_equalities_count": 1,
                  "derived_mjcf_sha256": hashlib.sha256(xml.encode()).hexdigest(),
                  "timestep_override_s": p.timestep_s, "artifact": "derived_model.xml",
                  "anchor_world_m": m.eq_data[-1, :3].tolist(), "solref": m.eq_solref[-1].tolist(),
                  "solimp": m.eq_solimp[-1].tolist(),
                  "reconstruction": "Pinned source plus recorded fixture parameters and timestep are authoritative; MjSpec XML export is diagnostic and may round floating-point attributes."}
    jid, aid = m.joint(p.joint).id, m.actuator(p.muscle).id
    qa, dof, act = int(m.jnt_qposadr[jid]), int(m.jnt_dofadr[jid]), int(m.actuator_actadr[aid])
    pelvis = m.body("pelvis").id
    origin = d.xpos[pelvis].copy()
    d.qvel[:] = 0
    d.act[:] = 0
    d.ctrl[:] = 0
    d.ctrl[aid] = p.excitation
    state_spec = mj.mjtState.mjSTATE_INTEGRATION
    state = np.empty(mj.mj_stateSize(m, state_spec))
    rows, poses, states = [], [], []
    d.qfrc_applied[dof] = controller_torque(0, float(d.qpos[qa]), 0, p.target_rad) if tracking else p.torque_Nm
    for step in range(p.steps + 1):
        if step:
            mj.mj_step(m, d)
        if tracking:
            d.qfrc_applied[dof] = controller_torque(float(d.time), float(d.qpos[qa]), float(d.qvel[dof]), p.target_rad)
        mj.mj_forward(m, d)
        if d.warning.number.any() or not all(np.isfinite(a).all() for a in (d.qpos, d.qvel, d.act, d.actuator_force)):
            raise ValueError("nonfinite state or engine warning in loaded experiment")
        if not 0 <= d.act[act] <= 1:
            raise ValueError("activation outside [0, 1]")
        if not m.jnt_range[jid, 0] - .01 <= d.qpos[qa] <= m.jnt_range[jid, 1] + .01:
            raise ValueError("loaded elbow left its model range beyond soft-limit tolerance 0.01 rad")
        rows.append({"sample": step, "time_s": float(d.time), "excitation": p.excitation,
            "activation": float(d.act[act]), "length_m": float(d.actuator_length[aid]),
            "actuator_force_N": float(d.actuator_force[aid]), "angle_rad": float(d.qpos[qa]),
            "velocity_rad_per_s": float(d.qvel[dof]), "applied_torque_Nm": float(d.qfrc_applied[dof]),
            "fixture_displacement_m": float(np.linalg.norm(d.xpos[pelvis] - origin))})
        if tracking:
            target, _ = reference_motion(float(d.time), p.target_rad)
            rows[-1].update({"target_angle_rad": target, "tracking_error_rad": target - float(d.qpos[qa])})
        poses.append(d.qpos.tolist())
        mj.mj_getState(m, d, state, state_spec)
        states.append(state.copy())
    times = np.array([r["time_s"] for r in rows])
    if abs(times[-1] - p.steps * p.timestep_s) > 1e-12:
        raise ValueError("time/step mismatch")
    work = p.torque_Nm * (rows[-1]["angle_rad"] - rows[0]["angle_rad"])
    trapezoid = float(np.trapezoid([r["applied_torque_Nm"] * r["velocity_rad_per_s"] for r in rows], times))
    bound = .5 * p.timestep_s * abs(p.torque_Nm * (rows[-1]["velocity_rad_per_s"] - rows[0]["velocity_rad_per_s"])) + 1e-9
    if tracking:
        work = sum(a["applied_torque_Nm"] * (b["angle_rad"] - a["angle_rad"]) for a, b in zip(rows, rows[1:]))
        trapezoid = sum(a["applied_torque_Nm"] * b["velocity_rad_per_s"] * p.timestep_s for a, b in zip(rows, rows[1:]))
        bound = 1e-9
    if abs(work - trapezoid) > bound:
        raise ValueError("independent power-integral / generalized-work comparison failed")
    with (output / "series.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    np.savez_compressed(output / "trajectory.npz", states=np.array(states), state_spec=int(state_spec),
                        time_s=times, qpos=np.array(poses))
    (output / "poses.json").write_text(json.dumps({"model_id": "ms_human_700", "method": "dynamic_forward",
        "simulation_time_s": float(d.time), "integration_steps": p.steps, "timestep_s": p.timestep_s,
        "time_s": times.tolist(), "qpos": poses, "joint_order": [m.joint(i).name for i in range(m.njnt)]}, indent=2))
    metrics = [{"name": "elapsed_time", "value": float(d.time), "unit": "s"},
               {"name": "final_angle", "value": rows[-1]["angle_rad"], "unit": "rad"},
               {"name": "final_activation", "value": rows[-1]["activation"], "unit": "1"},
               {"name": "final_actuator_force", "value": rows[-1]["actuator_force_N"], "unit": "N"},
               {"name": "applied_generalized_work", "value": work, "unit": "J", "definition": "constant applied joint torque times joint-angle change"},
               {"name": "integrated_applied_power", "value": trapezoid, "unit": "J", "definition": "trapezoidal integral of applied torque times joint velocity"},
               {"name": "work_quadrature_error_bound", "value": bound, "unit": "J", "definition": "Euler endpoint quadrature term plus 1e-9 J numerical tolerance"},
               {"name": "max_fixture_displacement", "value": max(r["fixture_displacement_m"] for r in rows), "unit": "m"}]
    if tracking:
        metrics[4]["definition"] = "Sum of held controller torque times angle increment over each Euler step"
        metrics[5]["name"] = "integrated_discrete_applied_power"
        metrics[5]["definition"] = "Sum of held controller torque times next-step velocity times dt; controller sample applies to the following interval"
        metrics[6]["definition"] = "Discrete work-accounting numerical tolerance; not total-system energy conservation"
        metrics += [{"name": "rms_tracking_error", "value": float(np.sqrt(np.mean([r["tracking_error_rad"]**2 for r in rows]))), "unit": "rad"},
                    {"name": "final_tracking_error", "value": rows[-1]["tracking_error_rad"], "unit": "rad"},
                    {"name": "max_control_torque", "value": max(abs(r["applied_torque_Nm"]) for r in rows), "unit": "N*m"}]
    (output / "summary.json").write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2))
    render_info = {"status": "not_requested", "render_backend": "none"}
    if p.render:
        try:
            from .visualization import render_motion
            render_info = render_motion(mj, m, output, jid, derivation)
        except Exception as exc:
            render_info = {"status": "failed", "render_backend": "none", "message": str(exc)[:1000]}
    result = {"status": "computed", "metrics": metrics, "render": render_info,
        "checks": [{"name": name, "status": "pass"} for name in ("finite_state", "zero_engine_warnings", "activation_bounds", "elapsed_time", "applied_work_power_integral")],
        "integration_steps": p.steps, "simulation_time_s": float(d.time), "integrator": mj.mjtIntegrator(int(m.opt.integrator)).name,
        "model_derivation": derivation,
        "limitations": ["Full model with an added soft pelvis fixture and prescribed elbow torque; not a person performing an exercise.",
                        "No floor, posture controller, equilibrium initialization, experimental force validation or clinical safety assessment.",
                        "Weld is compliant; actual pelvis displacement is reported. Other joints/muscles evolve under the source dynamics."],
        "initial_conditions": {"keyframe": "init", "qvel": "zero", "activation": "zero", "other_excitations": 0,
                               "fixture": derivation["fixture"], "applied_joint": p.joint, "applied_torque_Nm": p.torque_Nm,
                               "gravity_m_per_s2": m.opt.gravity.tolist(), "scene_floor": False},
        "counts": {"nq": m.nq, "nv": m.nv, "actuators": m.nu, "tendons": m.ntendon, "equality_constraints": m.neq},
        "timestep_s": p.timestep_s,
        "time_series": {"artifact_id": "series.csv", "axis": "time_s", "units": {"sample": "1", "time_s": "s", "excitation": "1", "activation": "1",
             "length_m": "m", "actuator_force_N": "N", "angle_rad": "rad", "velocity_rad_per_s": "rad/s", "applied_torque_Nm": "N*m", "fixture_displacement_m": "m"},
             "definition": "Full-model Euler dynamics with soft pelvis support and prescribed generalized elbow torque."}}
    if tracking:
        result["controller"] = {"type": "sampled_joint_pd", "kp_Nm_per_rad": 40, "kd_Nm_s_per_rad": 3,
                                "torque_limit_Nm": 8, "reference": "minimum-jerk 0-to-target ramp in 0.3 s, then hold through 0.4 s",
                                "actuation": "external generalized joint torque; not muscle-driven neural control",
                                "target_rad": p.target_rad, "sampling_s": p.timestep_s}
        result["limitations"] = ["Artificial soft pelvis support plus a bounded external PD joint servo; not an experimentally validated human motor controller or functional exercise.",
                                  "Reference is an engineering trajectory, not motion capture. Other source DOFs evolve without a posture controller or floor.",
                                  "Muscle excitation is constant and specified separately; the servo does not estimate biological activation, forces or movement safety."]
        result["initial_conditions"]["applied_torque_Nm"] = rows[0]["applied_torque_Nm"]
        result["initial_conditions"]["controller"] = result["controller"]
        result["time_series"]["units"].update({"target_angle_rad": "rad", "tracking_error_rad": "rad"})
        result["time_series"]["definition"] = "Real feedback-controlled full-model dynamics; torque at each recorded state is held over the following integration interval. Reference is synthetic engineering input."
    return result
