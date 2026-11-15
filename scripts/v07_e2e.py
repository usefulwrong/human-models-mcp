"""Real public-API pushup experiments, repeats, negative controls and state reconstruction."""

import csv
import json
import os
from uuid import uuid4

import numpy as np

from human_models_mcp.core import run_scenario
from human_models_mcp.registry import discover, home
from human_models_mcp.adapters.pushup import pushup_model, recruit, target_pose, transmission


def main():
    root = home()
    isolated = root / "reports/e2e-client-runs" / ("v07-science-" + str(uuid4()))
    isolated.mkdir(parents=True)
    for name in ("models", "scenarios", "models.lock.json", "requirements.lock", "runtime-environment.json"):
        (isolated / name).symlink_to(root / name)
    os.environ["HUMAN_MODELS_HOME"] = str(isolated)
    scenario = next(s for s in discover()["scenarios"] if s["id"] == "pushup")
    results = {}
    for name, params in (("muscle", {}), ("repeat", {}), ("external", {"control": "external"}),
                         ("zero_strength", {"muscle_strength_scale": 0.0}),
                         ("low_friction", {"friction": .05}), ("half_timestep", {"timestep_s": .0005})):
        run = run_scenario(scenario["id"], {"render": False, **params})
        assert run["status"] == "computed", run
        folder = home() / "results" / run["run_id"]
        results[name] = {"run_id": run["run_id"], "acceptance": run["scientific"]["acceptance"],
                         "summary": json.loads((folder / "summary.json").read_text()),
                         "artifacts": run["artifacts"]}
        print(name, results[name]["acceptance"], flush=True)
    source = home() / "results" / results["muscle"]["run_id"]
    repeat = home() / "results" / results["repeat"]["run_id"]
    saved, repeated = np.load(source / "trajectory.npz"), np.load(repeat / "trajectory.npz")
    difference = float(np.max(abs(saved["states"] - repeated["states"])))
    tolerance = scenario["validation"]["checks"]["repeat_run_absolute_tolerance"]
    assert difference <= tolerance
    assert results["muscle"]["acceptance"]["muscle_driven"] == "PASS"
    assert results["external"]["acceptance"]["muscle_driven"] == "NOT_ACHIEVED"
    assert results["zero_strength"]["acceptance"]["full_pushup"] == "FAIL"
    assert results["low_friction"]["acceptance"]["four_supports"] == "FAIL"
    assert results["half_timestep"]["acceptance"]["muscle_driven"] == "PASS"
    with (source / "series.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    mj, model, data = pushup_model(friction=scenario["defaults"]["friction"])
    worst_force = worst_power = worst_restart = worst_paths = 0.0
    reference = np.load(source / "reference.npz")["qpos"]
    active = np.array([j for j in range(6, model.njnt) if j not in model.eq_obj1id])
    for index in (0, 60, 120):
        mj.mj_setState(model, data, saved["states"][index], int(saved["state_spec"]))
        mj.mj_forward(model, data)
        assert not np.any(data.qfrc_applied) and not np.any(data.xfrc_applied)
        chunk = np.load(source / f"muscles_{index // 20:03d}.npz")
        j = index % 20
        assert np.array_equal(chunk["activation"][j], data.act)
        jac = np.zeros((700, model.nv))
        for act in range(700):
            start, count = chunk["moment_rowadr"][j, act], chunk["moment_rownnz"][j, act]
            jac[act, chunk["moment_columns"][j, start:start + count]] = chunk["moment_values"][j, start:start + count]
        worst_force = max(worst_force, float(np.max(abs(jac.T @ chunk["force_N"][j] - data.qfrc_actuator))))
        worst_power = max(worst_power, float(np.max(abs(chunk["power_W"][j] - chunk["force_N"][j] * chunk["velocity_m_per_s"][j]))))
        assert np.allclose(jac, transmission(model, data), rtol=0, atol=1e-12)
        # Independent finite difference for a genuine pectoralis transmission path.
        actuator, joint = model.actuator("PECM1_r").id, model.joint("shoulder_elv_r").id
        probes = []
        for sign in (-1, 1):
            scratch = mj.MjData(model)
            mj.mj_setState(model, scratch, saved["states"][index], int(saved["state_spec"]))
            scratch.qpos[joint] += sign * 1e-6
            mj.mj_forward(model, scratch)
            probes.append(scratch.actuator_length[actuator])
        worst_paths = max(worst_paths, float(abs((probes[1] - probes[0]) / 2e-6 - jac[actuator, joint])))
        if index < 120:
            # Restart and reproduce the next recorded state, crossing both controller updates.
            for restart_step in range(1, 21):
                mj.mj_step(model, data)
                mj.mj_forward(model, data)
                if restart_step % 10 == 0:
                    desired = np.clip(600 * (target_pose(reference, data.time)[active] - data.qpos[active]), -200, 200)
                    recruit(mj, model, data, active, desired)
                mj.mj_forward(model, data)
            worst_restart = max(worst_restart, float(np.max(abs(data.qpos - saved["qpos"][index + 1]))))
    assert worst_force < 1e-8 and worst_power < 1e-10 and worst_paths < 1e-6 and worst_restart < 1e-10
    half = home() / "results" / results["half_timestep"]["run_id"]
    with (half / "series.csv").open() as stream:
        half_rows = list(csv.DictReader(stream))
    time_difference = float(np.max(abs(np.array([float(r["angle_rad"]) for r in rows]) -
                                       np.array([float(r["angle_rad"]) for r in half_rows]))))
    assert time_difference < .1
    report = {"status": "pass", "store": str(isolated.relative_to(root)), "exercise": results["muscle"]["acceptance"], "experiments": results,
              "repeat_max_state_error": difference, "repeat_tolerance": tolerance,
              "max_sparse_force_error": worst_force, "max_power_error_W": worst_power,
              "max_restart_error": worst_restart, "max_pectoral_path_difference_error_m": worst_paths,
              "half_timestep_max_elbow_difference_rad": time_difference,
              "media": "separate independent MCP render client evidence; this script does not validate images"}
    destination = root / "reports/V07_E2E.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
