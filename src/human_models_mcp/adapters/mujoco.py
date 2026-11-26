"""MS-Human-700 prescribed pose measurements, not a motion controller."""

import csv
import hashlib
import json
import os

from pathlib import Path

from ..registry import SweepParameters, Validation, home
from ..runtime.graphics import actual_backend


MODEL_BODY = {
    "MS-Human-700.xml": "body_primary",
    "MS-Human-700-Manipulation.xml": "body_manipulation",
    "scene_locomotion.xml": "body_locomotion",
}


def model_assets(filename):
    root = home() / "models/ms_human_700"
    locked = json.loads((home() / "models.lock.json").read_text(encoding="utf-8"))
    assets = {}
    for item in locked["files"]:
        path = Path(item["path"]).relative_to("ms_human_700")
        # MuJoCo's VFS falls back to basenames for nested includes.
        if len(path.parts) > 2 and path.parts[1].startswith("body_") and path.parts[1] != MODEL_BODY[filename]:
            continue
        assets[path.as_posix()] = (root / path).read_bytes()
    return assets


def model_file(mj, filename, *, spec=False):
    if os.name != "nt":
        path = str(home() / "models/ms_human_700" / filename)
        return mj.MjSpec.from_file(path) if spec else mj.MjModel.from_xml_path(path)
    assets = model_assets(filename)
    with mj.MjVfs() as vfs:
        for name, contents in assets.items():
            vfs[name] = contents
        if not spec:
            return mj.MjModel.from_xml_path(filename, vfs=vfs)
        result = mj.MjSpec.from_file(filename, vfs=vfs)
    result.assets.update(assets)
    return result


def load(*, dense_constraints: bool = False, model_id: str = "ms_human_700"):
    import mujoco
    from ..catalog import MODEL_FILES

    model = model_file(mujoco, MODEL_FILES[model_id])
    if dense_constraints:
        model.opt.jacobian = mujoco.mjtJacobian.mjJAC_DENSE
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    return mujoco, model, data


def joint_record(m, index: int) -> dict:
    kind = ("free", "ball", "slide", "hinge")[int(m.jnt_type[index])]
    return {"name": m.joint(index).name, "type": kind, "limited": bool(m.jnt_limited[index]),
            "range": m.jnt_range[index].tolist() if kind != "free" else None,
            "unit": {"free": "m + unit_quaternion", "ball": "unit_quaternion", "slide": "m", "hinge": "rad"}[kind],
            "range_unit": "m" if kind == "slide" else "rad" if kind != "free" else None,
            "limit_semantics": "rotation cone" if kind == "ball" else "coordinate interval" if kind != "free" else "not applicable",
            "qpos_width": {"free": 7, "ball": 4, "slide": 1, "hinge": 1}[kind],
            "dof_width": {"free": 6, "ball": 3, "slide": 1, "hinge": 1}[kind]}


def inspect_model(joint: str | None = None, model_id: str = "ms_human_700") -> dict:
    mj, m, d = load(model_id=model_id)
    joints = [joint_record(m, i) for i in range(m.njnt)]
    if joint is not None:
        joints = [j for j in joints if j["name"] == joint]
        if not joints:
            return {"status": "unsupported", "error": {"code": "unsupported", "message": "unknown model joint"}}
    return {"status": "computed", "engine_version": mj.__version__, "nq": m.nq, "nv": m.nv,
            "joints_count": m.njnt, "bodies_including_world": m.nbody, "geoms": m.ngeom,
            "tendons": m.ntendon, "actuators": m.nu, "muscle_dynamics_actuators": int((m.actuator_dyntype == 4).sum()),
            "equality_constraints": m.neq, "contact_pairs": m.npair, "initial_contacts": d.ncon,
            "timestep_s": m.opt.timestep, "joints": joints,
            "muscles": [m.actuator(i).name for i in range(m.nu)],
            "evidence": "compiled pinned upstream model via MuJoCo; counts are not independent anatomical structures"}


def moment_entry(m, d, actuator: int, dof: int) -> float:
    # MuJoCo >=3.3 stores the actuator transmission Jacobian sparsely.
    start, count = int(d.moment_rowadr[actuator]), int(d.moment_rownnz[actuator])
    return sum(float(d.actuator_moment[i]) for i in range(start, start + count) if d.moment_colind[i] == dof)


def sweep(params: dict, output: Path, validation: dict, defaults: dict) -> dict:
    import numpy as np

    p = SweepParameters.model_validate(params)
    rules = Validation.model_validate(validation).checks
    coupled = p.coordinate_mode == "coupled_knee"
    mj, m, d = load(dense_constraints=coupled)
    jid = mj.mj_name2id(m, mj.mjtObj.mjOBJ_JOINT, p.joint)
    aid = mj.mj_name2id(m, mj.mjtObj.mjOBJ_ACTUATOR, p.muscle)
    if jid < 0 or aid < 0:
        return {"status": "unsupported", "error": {"code": "unsupported", "message": "joint or muscle absent from this model"}}
    if m.jnt_type[jid] != mj.mjtJoint.mjJNT_HINGE or m.actuator_trntype[aid] != mj.mjtTrn.mjTRN_TENDON:
        return {"status": "unsupported", "error": {"code": "unsupported", "message": "requires hinge joint and tendon transmission"}}
    lo, hi = m.jnt_range[jid]
    eps = rules.jacobian_central_difference.step_rad
    if m.jnt_limited[jid] and (p.start_rad - eps < lo or p.end_rad + eps > hi):
        return {"status": "invalid_input", "error": {"code": "invalid_input", "message": f"sweep plus derivative probes must fit model range [{lo}, {hi}] rad"}}
    from .knee import knee_equalities, set_path, constraint_checks, validate_interval
    try:
        equalities = knee_equalities(mj, m, d, jid) if coupled else []
        validate_interval(m, jid, equalities, p.start_rad - eps, p.end_rad + eps)
    except ValueError as exc:
        return {"status": "invalid_input", "error": {"code": "invalid_input", "message": str(exc)}}
    baseline = d.qpos.copy()
    rows, poses = [], []
    for index, angle in enumerate(np.linspace(p.start_rad, p.end_rad, p.samples)):
        tangent = set_path(m, d, baseline, jid, angle, equalities)
        mj.mj_forward(m, d)
        length = float(d.actuator_length[aid])
        jacobian = sum(moment_entry(m, d, aid, i) * value for i, value in enumerate(tangent) if value)
        residuals = constraint_checks(mj, m, d, jid, equalities, tangent) if coupled else {}
        probes = []
        for delta in (-eps, eps):
            set_path(m, d, baseline, jid, angle + delta, equalities)
            mj.mj_forward(m, d)
            probes.append(float(d.actuator_length[aid]))
        derivative = (probes[1] - probes[0]) / (2 * eps)
        set_path(m, d, baseline, jid, angle, equalities)
        mj.mj_forward(m, d)
        poses.append(d.qpos.tolist())
        rows.append({"sample": index, "angle_rad": float(angle), "length_m": length,
                     "moment_arm_m": -jacobian, "finite_difference_m_per_rad": derivative,
                     "jacobian_error_m_per_rad": abs(jacobian - derivative), **residuals})
    if not all(np.isfinite(list(r.values())).all() and r["length_m"] > 0 for r in rows):
        raise ValueError("non-finite output or nonpositive musculotendon path length")
    max_error = max(r["jacobian_error_m_per_rad"] for r in rows)
    tolerance = rules.jacobian_central_difference.absolute_tolerance_m_per_rad
    if max_error > tolerance:
        raise ValueError(f"moment-arm numerical consistency failed: {max_error} m/rad > {tolerance}")
    checks = [{"name": "finite_positive_path_lengths", "status": "pass"},
              {"name": "jacobian_central_difference", "status": "pass", "max_error": max_error,
               "unit": "m/rad", "tolerance": tolerance, "step_rad": eps}]
    if coupled:
        checks.append({"name": "local_knee_equalities_and_implicit_tangent", "status": "pass",
                       "equalities": [m.equality(i).name for i in equalities], "tolerance": 1e-9})
    matches_defaults = all(params[k] == defaults[k] for k in ("joint", "muscle", "start_rad", "end_rad", "samples", "coordinate_mode"))
    if rules.default_configuration is not None and matches_defaults:
        sign = rules.default_configuration
        change = rows[-1]["length_m"] - rows[0]["length_m"]
        direction = 1 if sign.path_length_change == "positive" else -1
        arm_sign = 1 if sign.signed_moment_arms == "positive" else -1
        if direction * change <= 0 or not all(arm_sign * row["moment_arm_m"] > 0 for row in rows):
            raise ValueError("declared default-configuration sign checks failed")
        checks.append({"name": "default_configuration", "status": "pass", **sign.model_dump()})
    with (output / "series.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    pose_record = {"model_id": "ms_human_700", "joint": p.joint, "muscle": p.muscle,
                   "method": "static_pose", "simulation_time_s": 0.0, "integration_steps": 0,
                   "timestep_s": m.opt.timestep, "qpos": poses,
                   "coordinate_mode": p.coordinate_mode,
                   "joint_order": [m.joint(i).name for i in range(m.njnt)]}
    (output / "poses.json").write_text(json.dumps(pose_record, indent=2), encoding="utf-8", newline="\n")
    metrics = [
        {"name": "length_start", "value": rows[0]["length_m"], "unit": "m"},
        {"name": "length_end", "value": rows[-1]["length_m"], "unit": "m"},
        {"name": "length_change", "value": rows[-1]["length_m"] - rows[0]["length_m"], "unit": "m",
         "definition": "length_end - length_start; musculotendon path, not isolated muscle fiber length"},
        {"name": "max_jacobian_error", "value": max_error, "unit": "m/rad",
         "definition": f"max |dL/dq from transmission Jacobian - central difference with h={eps} rad|"},
    ]
    if coupled:
        for field, unit in (("translation_residual_m", "m"), ("rotation_residual_rad", "rad"),
                            ("translation_tangent_error_m_per_rad", "m/rad"), ("rotation_tangent_error_rad_per_rad", "rad/rad")):
            metrics.append({"name": "max_" + field, "value": max(r[field] for r in rows), "unit": unit})
    (output / "summary.json").write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2), encoding="utf-8", newline="\n")
    render_info = {"status": "not_requested", "render_backend": "none"}
    if p.render:
        try:
            render_info = render(mj, m, d, output, poses[-1], p.samples - 1)
        except Exception as exc:
            render_info = {"status": "failed", "render_backend": "none", "message": str(exc)[:500]}
    return {"status": "computed", "metrics": metrics, "render": render_info, "checks": checks,
            "coordinate_mode": p.coordinate_mode,
            "counts": {"nq": m.nq, "nv": m.nv, "actuators": m.nu, "tendons": m.ntendon},
            "timestep_s": m.opt.timestep}


def render(mj, m, d, output: Path, qpos: list, sample: int, method: str = "static_pose", steps: int = 0) -> dict:
    from OpenGL import GL
    from PIL import Image

    m.vis.global_.offwidth, m.vis.global_.offheight = 640, 640
    m.vis.quality.shadowsize, m.vis.quality.offsamples = 512, 0
    d.qpos[:] = qpos
    mj.mj_forward(m, d)
    camera = mj.MjvCamera()
    camera.lookat[:] = [0, 0, 1.0]
    camera.distance, camera.azimuth, camera.elevation = 2.9, 135, -10
    with mj.Renderer(m, height=640, width=640) as renderer:
        renderer.update_scene(d, camera=camera)
        pixels = renderer.render()
        vendor = GL.glGetString(GL.GL_VENDOR).decode()
        device = GL.glGetString(GL.GL_RENDERER).decode()
        if pixels.std() < 1:
            raise ValueError("render is blank")
        Image.fromarray(pixels).save(output / "pose.png")
    backend = actual_backend(vendor)
    info = {"status": "rendered", "render_backend": backend, "gl_vendor": vendor, "gl_renderer": device,
            "model_id": "ms_human_700", "sample": sample, "simulation_time_s": float(d.time),
            "method": method, "timestep_s": m.opt.timestep, "integration_steps": steps, "qpos": qpos,
            "qpos_sha256": hashlib.sha256(json.dumps(qpos).encode()).hexdigest(),
            "qpos_hash_encoding": "UTF-8 json.dumps(qpos) with Python default separators",
            "width": 640, "height": 640, "camera": {"lookat": [0, 0, 1], "distance": 2.9, "azimuth": 135, "elevation": -10},
            "note": "Engine geometry from the recorded run state; no equilibrium or observed-human-motion claim."}
    (output / "frame.json").write_text(json.dumps(info, indent=2), encoding="utf-8", newline="\n")
    return info
