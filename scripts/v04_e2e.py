"""Real MCP tests for published-data comparison, feedback dynamics and exports."""

import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


async def artifact_bytes(call, run, name):
    artifact = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": name})
    assert artifact["status"] == "ok"
    data = base64.b64decode(artifact["data"], validate=True) if artifact["encoding"] == "base64" else artifact["data"].encode()
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"] == run["artifacts"][name]["sha256"]
    return data


async def rows(call, run):
    return list(csv.DictReader(io.StringIO((await artifact_bytes(call, run, "series.csv")).decode())))


async def exercise_v04(call, label):
    description = await call("describe_scenario", {"scenario_id": "elbow_tracking"})
    assert description["parameter_schema"]["properties"]["target_rad"]["maximum"] == .6
    assert (await call("get_model_capabilities", {"model_id": "ms_human_700", "quantity": "defecation"}))["reason"] == "known_unsupported"
    assert (await call("get_model_capabilities", {"model_id": "ms_human_700", "quantity": "invented"}))["reason"] == "unknown_quantity"
    sources = await call("search_sources", {"query": "Nichols"})
    assert any(item["evidence_type"] == "published_experimental_aggregate" and item["license"] == "CC0-1.0" for item in sources["matches"])
    benchmark = await call("run_scenario", {"scenario_id": "wrist_benchmark"})
    assert benchmark["status"] == "computed", benchmark
    assert benchmark["execution"]["integration_steps"] == 0
    assert benchmark["scientific"]["validation_level"] == "numerical_sanity"
    assert benchmark["model"]["integrity"] == "sha256_verified_for_execution"
    comparison = json.loads(await artifact_bytes(call, benchmark, "comparison.json"))
    data = await rows(call, benchmark)
    article = ET.fromstring(await artifact_bytes(call, benchmark, "reference_article.xml"))
    assert hashlib.sha256(await artifact_bytes(call, benchmark, "experimental_reference.csv")).hexdigest() == comparison["source"]["files"]["reference.csv"]
    table = next(item for item in article.findall(".//table-wrap") if item.get("id") == "pone.0157346.t002")
    for tr in table.findall(".//tbody/tr")[:5]:
        cells = ["".join(item.itertext()).strip() for item in tr.findall("td")]
        for axis, index in (("extension", 1), ("ulnar_deviation", 4)):
            mean, sd = map(float, re.fullmatch(r"(-?[\d.]+) \(([\d.]+)\)", cells[index]).groups())
            row = next(item for item in data if item["muscle"] == cells[0] and item["axis"] == axis)
            assert float(row["experimental_mean_m"]) == mean * .01 and float(row["experimental_sd_m"]) == sd * .01
    assert len(data) == 10 and max(float(row["jacobian_error_m_per_rad"]) for row in data) < 1e-7
    assert max(abs(x) for x in comparison["neutral_geometric_angles_rad"]) < 1e-10
    repeat = await call("run_scenario", {"scenario_id": "wrist_benchmark", "parameters": {"render": False}})
    assert repeat["status"] == "computed" and await rows(call, repeat) == data
    for params in ({"reference_id": "other"}, {"samples": 11}):
        rejected = await call("run_scenario", {"scenario_id": "wrist_benchmark", "parameters": params})
        assert rejected["status"] == "invalid_input"

    tracking = await call("run_scenario", {"scenario_id": "elbow_tracking"})
    assert tracking["status"] == "computed", tracking
    trace = await rows(call, tracking)
    repeat = await call("run_scenario", {"scenario_id": "elbow_tracking", "parameters": {"render": False}})
    refined = await call("run_scenario", {"scenario_id": "elbow_tracking", "parameters": {"render": False, "steps": 400, "timestep_s": .001}})
    control = await call("run_scenario", {"scenario_id": "loaded_elbow", "parameters": {"render": False, "steps": 200, "excitation": 0.0, "torque_Nm": 0.0}})
    assert repeat["status"] == refined["status"] == control["status"] == "computed", (repeat, refined, control)
    assert trace == await rows(call, repeat)
    uncontrolled = await rows(call, control)
    assert len(trace) == 201 and abs(float(trace[-1]["time_s"]) - .4) < 1e-12
    for row in trace:
        time = float(row["time_s"])
        u = min(time / .3, 1)
        target = .4 * (10*u**3 - 15*u**4 + 6*u**5)
        velocity = .4/.3 * (30*u**2-60*u**3+30*u**4) if u < 1 else 0
        angle, speed = float(row["angle_rad"]), float(row["velocity_rad_per_s"])
        torque = max(-8, min(8, 40*(target-angle)+3*(velocity-speed)))
        assert abs(target - float(row["target_angle_rad"])) < 1e-12
        assert abs(torque - float(row["applied_torque_Nm"])) < 1e-12
    rms = float(np.sqrt(np.mean([float(row["tracking_error_rad"])**2 for row in trace])))
    control_rms = float(np.sqrt(np.mean([(float(t["target_angle_rad"]) - float(c["angle_rad"]))**2 for t, c in zip(trace, uncontrolled, strict=True)])))
    assert rms < .05 and rms < control_rms and abs(float(trace[-1]["tracking_error_rad"])) < .02
    refined_rows = await rows(call, refined)
    refinement = abs(float(trace[-1]["angle_rad"]) - float(refined_rows[-1]["angle_rad"]))
    assert refinement < .005
    work = sum(float(a["applied_torque_Nm"]) * (float(b["angle_rad"]) - float(a["angle_rad"])) for a, b in zip(trace, trace[1:]))
    metric = next(item for item in tracking["outputs"]["metrics"] if item["name"] == "applied_generalized_work")
    assert metric["unit"] == "J" and abs(work - metric["value"]) < 1e-12
    for params in ({"steps": 300}, {"target_rad": 2.0}, {"torque_Nm": 1.0}):
        assert (await call("run_scenario", {"scenario_id": "elbow_tracking", "parameters": params}))["status"] == "invalid_input"

    saved = np.load(io.BytesIO(await artifact_bytes(call, tracking, "trajectory.npz")), allow_pickle=False)
    import mujoco as mj
    spec = mj.MjSpec.from_file(str(ROOT / "models/ms_human_700/MS-Human-700.xml"))
    recipe = tracking["model"]["derivation"]
    spec.option.timestep = .002
    fixture = spec.add_equality(name="fixture_pelvis", type=mj.mjtEq.mjEQ_WELD,
                               objtype=mj.mjtObj.mjOBJ_BODY, name1="pelvis", name2="world")
    fixture.data[:3], fixture.solref[:], fixture.solimp[:] = recipe["anchor_world_m"], recipe["solref"], recipe["solimp"]
    model = spec.compile()
    native = mj.MjData(model)
    for index in (0, 100, 199):
        mj.mj_setState(model, native, saved["states"][index], int(saved["state_spec"]))
        mj.mj_step(model, native)
        np.testing.assert_allclose(native.qpos, saved["qpos"][index+1], rtol=0, atol=1e-12)
    frame = json.loads(await artifact_bytes(call, tracking, "frames.json"))
    assert frame["qpos_hash_encoding"].startswith("UTF-8 json.dumps") and frame["state_hash_encoding"]["order"] == "C"
    for item in frame["frames"]:
        assert item["state_sha256"] == hashlib.sha256(saved["states"][item["state_index"]].tobytes()).hexdigest()
    path = ROOT / "examples/mcp-client/artifacts.py"
    module_spec = importlib.util.spec_from_file_location("client_export", path)
    exporter = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(exporter)
    destination = ROOT / "reports/e2e-client-runs" / ("export-" + label)
    viewer = await exporter.export_run(call, tracking, destination)
    assert viewer.is_file() and "dynamic_forward" in viewer.read_text()
    assert json.loads((destination / "manifest.json").read_text()) == tracking
    for name, metadata in tracking["artifacts"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == metadata["sha256"]
    return {"benchmark": {"run": benchmark, "csv": data, "checks": ["published_table_values", "reference_hashes", "geometric_neutral", "physical_angle_finite_difference", "repeatability", "no_fitting"]},
            "tracking": {"run": tracking, "rms_error_rad": rms, "uncontrolled_rms_error_rad": control_rms,
                         "refinement_difference_rad": refinement, "repeat_run_id": repeat["run_id"], "refined_run_id": refined["run_id"],
                         "control_run_id": control["run_id"], "export": str(destination.relative_to(ROOT)),
                         "checks": ["actual_feedback_law", "numeric_trajectory", "control_ablation", "timestep_refinement", "repeatability", "discrete_work", "independent_state_restart", "state_frame_hashes", "complete_mcp_artifact_export"]}}
