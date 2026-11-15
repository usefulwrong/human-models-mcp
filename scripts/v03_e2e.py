"""Additional public-MCP scientific checks; no use of the server's Python API."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image


async def series(call, run):
    artifact = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "series.csv"})
    assert hashlib.sha256(artifact["data"].encode()).hexdigest() == artifact["sha256"]
    return list(csv.DictReader(io.StringIO(artifact["data"])))


async def exercise_v03(call):
    joint = await call("search_sources", {"query": "knee_angle_r", "limit": 10})
    assert any(r["id"] == "knee_angle_r" and r["evidence_type"] == "upstream_joint_identifier" for r in joint["matches"])
    coupled = await call("run_scenario", {"scenario_id": "knee_coupled"})
    assert coupled["status"] == "computed", coupled
    assert coupled["execution"]["coordinate_mode"] == "coupled_knee"
    rows = await series(call, coupled)
    for field in ("translation_residual_m", "rotation_residual_rad", "translation_tangent_error_m_per_rad", "rotation_tangent_error_rad_per_rad"):
        assert max(float(r[field]) for r in rows) < 1e-9
    assert max(float(r["jacobian_error_m_per_rad"]) for r in rows) < 1e-7
    fixed = await call("run_scenario", {"scenario_id": "knee_sweep", "parameters": {"end_rad": .6, "render": False}})
    assert fixed["status"] == "computed", fixed
    fixed_rows = await series(call, fixed)
    assert [r["angle_rad"] for r in rows] == [r["angle_rad"] for r in fixed_rows]
    difference = max(abs(float(a["moment_arm_m"]) - float(b["moment_arm_m"])) for a, b in zip(rows, fixed_rows, strict=True))
    assert difference > 1e-4
    for params in ({"end_rad": 1.0}, {"joint": "elbow_flexion_r"}):
        rejected = await call("run_scenario", {"scenario_id": "knee_coupled", "parameters": params})
        assert rejected["status"] == "invalid_input" and not rejected["outputs"]["metrics"], rejected
    repeat = await call("run_scenario", {"scenario_id": "knee_coupled", "parameters": {"render": False}})
    assert repeat["status"] == "computed" and rows == await series(call, repeat)

    loaded = await call("run_scenario", {"scenario_id": "loaded_elbow"})
    assert loaded["status"] == "computed", loaded
    assert loaded["execution"]["physics_backend"] == "cpu" and loaded["counts"]["equality_constraints"] == 43
    data = await series(call, loaded)
    assert len(data) == 101 and abs(float(data[-1]["time_s"]) - .2) < 1e-12
    assert float(data[0]["angle_rad"]) == float(data[0]["velocity_rad_per_s"]) == 0
    assert float(data[-1]["angle_rad"]) > .1
    assert max(float(r["fixture_displacement_m"]) for r in data) < .002
    metrics = {m["name"]: m["value"] for m in loaded["outputs"]["metrics"]}
    work = 2 * (float(data[-1]["angle_rad"]) - float(data[0]["angle_rad"]))
    power_work = float(np.trapezoid([2 * float(r["velocity_rad_per_s"]) for r in data], [float(r["time_s"]) for r in data]))
    assert abs(metrics["applied_generalized_work"] - work) < 1e-12
    assert abs(power_work - work) <= metrics["work_quadrature_error_bound"]
    repeats = []
    for params in ({"render": False}, {"render": False, "torque_Nm": 0.0},
                   {"render": False, "steps": 200, "timestep_s": .001}):
        result = await call("run_scenario", {"scenario_id": "loaded_elbow", "parameters": params})
        assert result["status"] == "computed", result
        repeats.append(result)
    assert data == await series(call, repeats[0])
    control, refined = [await series(call, result) for result in repeats[1:]]
    load_response = float(data[-1]["angle_rad"]) - float(control[-1]["angle_rad"])
    refinement_difference = abs(float(data[-1]["angle_rad"]) - float(refined[-1]["angle_rad"]))
    assert load_response > .05
    assert refinement_difference < .005  # Regression bound in rad, not a physiological accuracy claim.
    for params in ({"torque_Nm": 6.0}, {"steps": 201}, {"timestep_s": .01}, {"muscle": "absent"}):
        rejected = await call("run_scenario", {"scenario_id": "loaded_elbow", "parameters": params})
        assert rejected["status"] == "invalid_input" and not rejected.get("outputs", {}).get("metrics")

    artifacts = {}
    for name in loaded["artifacts"]:
        artifact = await call("get_artifact", {"run_id": loaded["run_id"], "artifact_id": name})
        content = base64.b64decode(artifact["data"]) if artifact["encoding"] == "base64" else artifact["data"].encode()
        assert hashlib.sha256(content).hexdigest() == loaded["artifacts"][name]["sha256"] == artifact["sha256"]
        artifacts[name] = content
        if name.endswith(".png"):
            with Image.open(io.BytesIO(content)) as picture:
                picture.verify()
    saved = np.load(io.BytesIO(artifacts["trajectory.npz"]), allow_pickle=False)
    poses = json.loads(artifacts["poses.json"])
    metadata = json.loads(artifacts["frames.json"])
    assert np.array_equal(saved["qpos"], np.array(poses["qpos"]))
    assert metadata["state_archive_sha256"] == hashlib.sha256(artifacts["trajectory.npz"]).hexdigest()
    assert metadata["derived_mjcf_sha256"] == hashlib.sha256(artifacts["derived_model.xml"]).hexdigest()
    for frame in metadata["frames"]:
        index = frame["state_index"]
        assert frame["state_sha256"] == hashlib.sha256(saved["states"][index].tobytes()).hexdigest()
        assert frame["time_s"] == saved["time_s"][index]
        assert frame["sha256"] == hashlib.sha256(artifacts[frame["artifact_id"]]).hexdigest()
    # Reconstruct independently from pinned files + public recipe, without importing the adapter.
    import mujoco as mj
    source = Path(__file__).resolve().parents[1] / "models/ms_human_700/MS-Human-700.xml"
    model_spec = mj.MjSpec.from_file(str(source))
    recipe = loaded["model"]["derivation"]
    model_spec.option.timestep = loaded["execution"]["timestep_s"]
    fixture = model_spec.add_equality(name="fixture_pelvis", type=mj.mjtEq.mjEQ_WELD,
                                    objtype=mj.mjtObj.mjOBJ_BODY, name1="pelvis", name2="world")
    fixture.data[:3] = recipe["anchor_world_m"]
    fixture.solref[:] = recipe["solref"]
    fixture.solimp[:] = recipe["solimp"]
    model = model_spec.compile()
    native = mj.MjData(model)
    slide = np.array([int(model.jnt_qposadr[i]) for i in range(model.njnt) if model.jnt_type[i] == mj.mjtJoint.mjJNT_SLIDE])
    hinge = np.array([int(model.jnt_qposadr[i]) for i in range(model.njnt) if model.jnt_type[i] == mj.mjtJoint.mjJNT_HINGE])
    restart_errors = {"translation_m": 0.0, "rotation_rad": 0.0}
    for index in (0, 50, 99):
        mj.mj_setState(model, native, saved["states"][index], int(saved["state_spec"]))
        mj.mj_step(model, native)
        error = np.abs(native.qpos - saved["qpos"][index + 1])
        for key, coordinates in (("translation_m", slide), ("rotation_rad", hinge)):
            restart_errors[key] = max(restart_errors[key], float(np.max(error[coordinates])))
    assert all(value < 1e-12 for value in restart_errors.values())
    mj.mj_setState(model, native, saved["states"][-1], int(saved["state_spec"]))
    mj.mj_forward(model, native)
    summed_torque = np.zeros(model.nv)
    for actuator in range(model.nu):
        start, count = int(native.moment_rowadr[actuator]), int(native.moment_rownnz[actuator])
        for entry in range(start, start + count):
            summed_torque[native.moment_colind[entry]] += native.actuator_moment[entry] * native.actuator_force[actuator]
    force_error = np.abs(summed_torque - native.qfrc_actuator)
    transmission_errors = {"slide_N": float(np.max(force_error[slide])), "hinge_Nm": float(np.max(force_error[hinge]))}
    assert all(value < 1e-9 for value in transmission_errors.values())
    model.vis.global_.offwidth, model.vis.global_.offheight = 640, 480
    model.vis.quality.shadowsize, model.vis.quality.offsamples = 512, 0
    camera = mj.MjvCamera()
    for name, value in metadata["camera"].items():
        if name == "lookat":
            camera.lookat[:] = value
        else:
            setattr(camera, name, value)
    option = mj.MjvOption()
    option.flags[mj.mjtVisFlag.mjVIS_JOINT] = True
    with mj.Renderer(model, height=480, width=640) as renderer:
        renderer.update_scene(native, camera=camera, scene_option=option)
        independent_pixels = renderer.render()
    with Image.open(io.BytesIO(artifacts[metadata["frames"][-1]["artifact_id"]])) as original:
        assert np.array_equal(np.array(original), independent_pixels)
    with Image.open(io.BytesIO(artifacts["animation.gif"])) as animation:
        assert animation.n_frames == len(metadata["frames"]) == 21
        assert animation.size == (1120, 548)
        animation.seek(animation.n_frames - 1)
        animation.load()
    return {"coupled_knee": {"run": coupled, "csv": rows, "fixed_comparison_run": fixed["run_id"],
                "max_effective_vs_partial_arm_difference_m": difference, "repeat_run_id": repeat["run_id"],
                "checks": ["source_equalities", "implicit_constraint_jacobian", "path_finite_difference", "range_extrema_rejection", "repeatability"]},
            "loaded_elbow": {"run": loaded, "repeat_run_id": repeats[0]["run_id"], "control_run_id": repeats[1]["run_id"],
                "refined_run_id": repeats[2]["run_id"], "csv": data, "load_response_rad": load_response,
                "independent_restart_errors": restart_errors, "transmission_sum_errors": transmission_errors,
                "timestep_refinement_difference_rad": refinement_difference, "refinement_regression_bound_rad": .005,
                "checks": ["true_full_model_dynamics", "explicit_fixture", "work_power_integral", "load_control", "timestep_refinement", "repeatability", "saved_states", "independent_state_restart", "independent_transmission_sum", "independent_pixel_reconstruction", "all_artifact_hashes", "png_and_gif_decode", "21_frames"]}}
