"""Real SDK clients + real pinned MuJoCo model, offline in the release container."""

import asyncio
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

from mcp import Client, StdioServerParameters
from PIL import Image, ImageStat
from v03_e2e import exercise_v03
from v04_e2e import exercise_v04
from v05_e2e import exercise_v05

ROOT = Path(__file__).resolve().parents[1]


async def exercise_forward(call):
    scenario = await call("describe_scenario", {"scenario_id": "activation_pulse"})
    assert scenario["method"] == "dynamic_forward"
    for parameters, expected in [({"steps": 26}, "invalid_input"), ({"excitation": 1.1}, "invalid_input"),
                                  ({"muscle": "nonexistent_muscle"}, "unsupported")]:
        rejected = await call("run_scenario", {"scenario_id": "activation_pulse", "parameters": parameters})
        assert rejected["status"] == expected and not rejected.get("outputs", {}).get("metrics")
    run = await call("run_scenario", {"scenario_id": "activation_pulse"})
    assert run["status"] == "computed", run
    repeat = await call("run_scenario", {"scenario_id": "activation_pulse", "parameters": {"render": False}})
    control = await call("run_scenario", {"scenario_id": "activation_pulse", "parameters": {"excitation": 0.0, "render": False}})
    assert repeat["status"] == control["status"] == "computed"
    assert len({run["run_id"], repeat["run_id"], control["run_id"]}) == 3
    tolerance = scenario["validation"]["checks"]["repeat_run_absolute_tolerance"]
    for a, b in zip(run["outputs"]["metrics"], repeat["outputs"]["metrics"], strict=True):
        assert a["unit"] == b["unit"] and abs(a["value"] - b["value"]) <= tolerance
    artifact = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "series.csv"})
    other = await call("get_artifact", {"run_id": repeat["run_id"], "artifact_id": "series.csv"})
    assert hashlib.sha256(artifact["data"].encode()).hexdigest() == artifact["sha256"] == other["sha256"]
    rows = list(csv.DictReader(io.StringIO(artifact["data"])))
    assert len(rows) == 11 and float(rows[0]["time_s"]) == 0
    assert abs(float(rows[-1]["time_s"]) - 0.02) < 1e-12
    assert all(0 <= float(r["activation"]) <= 1 and float(r["length_m"]) > 0 for r in rows)
    assert all(float(b["time_s"]) > float(a["time_s"]) for a, b in zip(rows, rows[1:]))
    assert float(rows[-1]["activation"]) > float(rows[0]["activation"])
    control_metrics = {m["name"]: m["value"] for m in control["outputs"]["metrics"]}
    assert control_metrics["final_activation"] == 0
    assert abs(float(rows[-1]["actuator_force_N"])) > abs(control_metrics["final_actuator_force"])
    assert run["execution"]["integration_steps"] == 10 and run["execution"]["physics_backend"] == "cpu"
    assert run["execution"]["integrator"] == "mjINT_EULER"
    assert all(c["status"] == "pass" for c in run["scientific"]["checks"])
    assert run["outputs"]["time_series"][0]["units"]["actuator_force_N"] == "N"
    frame = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "frame.json"}))["data"])
    poses = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "poses.json"}))["data"])
    assert frame["qpos"] == poses["qpos"][-1] and frame["qpos"] != poses["qpos"][0]
    assert frame["method"] == "dynamic_forward" and frame["integration_steps"] == 10
    assert abs(frame["simulation_time_s"] - float(rows[-1]["time_s"])) < 1e-12
    image = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "pose.png"})
    binary = base64.b64decode(image["data"])
    assert hashlib.sha256(binary).hexdigest() == image["sha256"]
    with Image.open(io.BytesIO(binary)) as picture:
        picture.verify()
    return {"run": run, "repeat_run_id": repeat["run_id"], "control": control,
            "csv": rows, "checks": ["real_integration", "elapsed_time", "activation_response", "zero_excitation_control",
                                    "signed_force_units", "finite_state", "repeatability", "matching_dynamic_pose"]}


async def exercise(source, label):
    async with Client(source, read_timeout_seconds=120) as client:
        tool_names = {t.name for t in (await client.list_tools()).tools}
        assert {"list_models", "describe_model", "get_model_capabilities", "get_joint_info", "list_scenarios",
                "describe_scenario", "run_scenario", "get_result", "get_artifact"} <= tool_names

        async def call(name, arguments=None):
            r = await client.call_tool(name, arguments or {})
            assert not r.is_error, r
            assert r.structured_content is not None, r
            return r.structured_content

        models = await call("list_models")
        assert models["models"][0]["status"] == "available"
        card = await call("describe_model", {"model_id": "ms_human_700"})
        assert card["revision"] == "98a70c569c4c1b6da467a20012f766ee1f8dc521"
        sources = await call("search_sources", {"query": "BIClong_r"})
        assert sources["status"] == "ok" and sources["offline"] and sources["backend"] == "sqlite_fts5"
        term = next(m for m in sources["matches"] if m["id"] == "BIClong_r")
        assert term["version"] == card["revision"] and term["license"] == "Apache-2.0" and len(term["source_sha256"]) == 64
        assert (await call("search_sources", {"query": "zzzzunknownanatomy"}))["matches"] == []
        assert (await call("search_sources", {"query": "*****"}))["status"] == "invalid_input"
        assert (await call("describe_model", {"model_id": "uninstalled"}))["status"] == "unsupported"
        info = await call("get_joint_info", {"model_id": "ms_human_700", "joint": "elbow_flexion_r"})
        assert info["nv"] == 85 and info["actuators"] == 700 and info["muscle_dynamics_actuators"] == 700
        assert info["joints"][0]["unit"] == "rad" and info["joints"][0]["range"] == [0.0, 2.2]
        for quantity in ("disc_pressure", "spinal_cord", "breathing", "medical_safety", "injury_risk"):
            r = await call("get_model_capabilities", {"model_id": "ms_human_700", "quantity": quantity})
            assert r["status"] == "unsupported" and "metrics" not in r
        scenarios = await call("list_scenarios")
        assert "external_check" in [s["id"] for s in scenarios["scenarios"]]
        assert "broken_check" in [s["id"] for s in scenarios["quarantined"]]
        assert "bad_validation_check" in [s["id"] for s in scenarios["quarantined"]]
        assert (await call("describe_scenario", {"scenario_id": "elbow_sweep"}))["method"] == "static_pose"
        for arguments, status in [
            ({"scenario_id": "unknown_exercise"}, "unsupported"),
            ({"scenario_id": "elbow_sweep", "parameters": {"samples": 100000}}, "invalid_input"),
            ({"scenario_id": "elbow_sweep", "parameters": {"samples": True}}, "invalid_input"),
            ({"scenario_id": "elbow_sweep", "parameters": {"start_rad": 2.1, "end_rad": 0.2}}, "invalid_input"),
            ({"scenario_id": "elbow_sweep", "parameters": {"end_rad": 2.5}}, "invalid_input"),
            ({"scenario_id": "elbow_sweep", "parameters": {"muscle": "imaginary_organ"}}, "unsupported"),
            ({"scenario_id": "elbow_sweep", "parameters": {"joint": "../etc/passwd"}}, "unsupported"),
            ({"scenario_id": "elbow_sweep", "parameters": {"command": "echo unsafe"}}, "invalid_input"),
        ]:
            r = await call("run_scenario", arguments)
            assert r["status"] == status and not r.get("outputs", {}).get("metrics"), r
        a = await call("run_scenario", {"scenario_id": "elbow_sweep", "idempotency_key": label})
        assert a["status"] == "computed", a
        contract = json.loads((await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "validation.json"}))["data"])
        assert contract == (await call("describe_scenario", {"scenario_id": "elbow_sweep"}))["validation"]
        assert {c["name"] for c in a["scientific"]["checks"]} == {"finite_positive_path_lengths", "jacobian_central_difference", "default_configuration"}
        bad_sign = await call("run_scenario", {"scenario_id": "bad_sign_check", "parameters": {"render": False}})
        assert bad_sign["status"] == "failed" and bad_sign["scientific"]["validation_level"] == "unvalidated"
        assert bad_sign["outputs"]["metrics"] == []
        again = await call("run_scenario", {"scenario_id": "elbow_sweep", "idempotency_key": label})
        assert a == again
        conflict = await call("run_scenario", {"scenario_id": "elbow_sweep", "idempotency_key": label,
                                               "parameters": {"samples": 5}})
        assert conflict["status"] == "invalid_input"
        b = await call("run_scenario", {"scenario_id": "external_check", "parameters": {"render": False}})
        assert b["status"] == "computed" and a["run_id"] != b["run_id"], b
        for first, second in zip(a["outputs"]["metrics"], b["outputs"]["metrics"], strict=True):
            assert first["unit"] == second["unit"] and abs(first["value"] - second["value"]) <= contract["checks"]["repeat_run_absolute_tolerance_m"]
        assert (await call("get_result", {"run_id": a["run_id"]})) == a
        csv_data = await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "series.csv"})
        assert hashlib.sha256(csv_data["data"].encode()).hexdigest() == csv_data["sha256"]
        rows = list(csv.DictReader(io.StringIO(csv_data["data"])))
        assert len(rows) == 9
        assert all(float(r["length_m"]) > 0 for r in rows)
        assert float(rows[-1]["length_m"]) < float(rows[0]["length_m"])
        assert max(float(r["jacobian_error_m_per_rad"]) for r in rows) < 1e-5
        assert all(float(r["moment_arm_m"]) > 0 for r in rows)
        assert a["execution"]["physics_backend"] == "cpu" and a["engine"]["version"] == "3.17.0"
        assert a["execution"]["integration_steps"] == 0
        assert a["scientific"]["validation_level"] == "numerical_sanity"
        assert (await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "../../etc/passwd"}))["status"] == "invalid_input"
        assert (await call("get_result", {"run_id": "../../etc/passwd"}))["status"] == "invalid_input"
        assert a["outputs"]["images"], a.get("render")
        image = await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "pose.png"})
        binary = base64.b64decode(image["data"])
        assert hashlib.sha256(binary).hexdigest() == image["sha256"]
        with Image.open(io.BytesIO(binary)) as picture:
            picture.verify()
        with Image.open(io.BytesIO(binary)) as picture:
            assert picture.format == "PNG" and picture.size == (640, 640)
            assert max(ImageStat.Stat(picture).stddev) > 1
        frame = json.loads((await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "frame.json"}))["data"])
        poses = json.loads((await call("get_artifact", {"run_id": a["run_id"], "artifact_id": "poses.json"}))["data"])
        assert frame["qpos"] == poses["qpos"][-1] and frame["sample"] == 8 and frame["simulation_time_s"] == 0
        assert frame["model_id"] == a["model"]["id"] and frame["timestep_s"] == a["execution"]["timestep_s"]
        knee_scenario = await call("describe_scenario", {"scenario_id": "knee_sweep"})
        assert knee_scenario["defaults"]["joint"] == "knee_angle_r"
        assert knee_scenario["defaults"]["muscle"] == "recfem_r"
        knee_info = await call("get_joint_info", {"model_id": "ms_human_700", "joint": "knee_angle_r"})
        assert knee_info["joints"][0]["range"] == [0.0, 2.4]
        knee = await call("run_scenario", {"scenario_id": "knee_sweep"})
        assert knee["status"] == "computed", knee
        knee_repeat = await call("run_scenario", {"scenario_id": "knee_sweep", "parameters": {"render": False}})
        assert knee_repeat["status"] == "computed" and knee_repeat["run_id"] != knee["run_id"], knee_repeat
        for first, second in zip(knee["outputs"]["metrics"], knee_repeat["outputs"]["metrics"], strict=True):
            assert first["unit"] == second["unit"] and abs(first["value"] - second["value"]) <= 1e-12
        knee_csv = await call("get_artifact", {"run_id": knee["run_id"], "artifact_id": "series.csv"})
        knee_repeat_csv = await call("get_artifact", {"run_id": knee_repeat["run_id"], "artifact_id": "series.csv"})
        assert hashlib.sha256(knee_csv["data"].encode()).hexdigest() == knee_csv["sha256"] == knee_repeat_csv["sha256"]
        knee_rows = list(csv.DictReader(io.StringIO(knee_csv["data"])))
        assert len(knee_rows) == 9
        assert all(float(r["length_m"]) > 0 and float(r["moment_arm_m"]) < 0 for r in knee_rows)
        assert all(float(v["length_m"]) > float(u["length_m"]) for u, v in zip(knee_rows, knee_rows[1:]))
        assert max(float(r["jacobian_error_m_per_rad"]) for r in knee_rows) < 1e-5
        assert knee["model"] == a["model"] and knee["engine"] == a["engine"]
        assert knee["execution"]["method"] == "static_pose" and knee["execution"]["physics_backend"] == "cpu"
        assert knee["scientific"]["validation_level"] == "numerical_sanity"
        assert knee["outputs"]["images"], knee.get("render")
        knee_png = await call("get_artifact", {"run_id": knee["run_id"], "artifact_id": "pose.png"})
        knee_pixels = base64.b64decode(knee_png["data"])
        assert hashlib.sha256(knee_pixels).hexdigest() == knee_png["sha256"]
        with Image.open(io.BytesIO(knee_pixels)) as picture:
            picture.verify()
        with Image.open(io.BytesIO(knee_pixels)) as picture:
            assert picture.size == (640, 640) and max(ImageStat.Stat(picture).stddev) > 1
        knee_frame = json.loads((await call("get_artifact", {"run_id": knee["run_id"], "artifact_id": "frame.json"}))["data"])
        knee_poses = json.loads((await call("get_artifact", {"run_id": knee["run_id"], "artifact_id": "poses.json"}))["data"])
        assert knee_frame["qpos"] == knee_poses["qpos"][-1] and knee_frame["sample"] == 8
        assert knee_frame["model_id"] == knee["model"]["id"] and knee_frame["simulation_time_s"] == 0
        assert knee_frame["timestep_s"] == knee["execution"]["timestep_s"] and knee_frame["integration_steps"] == 0
        coordinate = knee_poses["joint_order"].index("knee_angle_r")
        for row, pose in zip(knee_rows, knee_poses["qpos"], strict=True):
            assert pose[coordinate] == float(row["angle_rad"])
            assert all(value == knee_poses["qpos"][0][i] for i, value in enumerate(pose) if i != coordinate)
        forward = await exercise_forward(call)
        v03 = await exercise_v03(call)
        v04 = await exercise_v04(call, label)
        v05 = await exercise_v05(call, label)
        result = {"status": "pass", "transport": label, "protocol": str(client.protocol_version),
                  "tools": sorted(tool_names), "run": a, "repeat_run_id": b["run_id"],
                  "repeat_absolute_tolerance": 1e-12, "csv": rows, "png_bytes": len(binary),
                  "model_inspection": {k: v for k, v in info.items() if k != "muscles"},
                  "gates": ["discovery", "real_model", "units_provenance", "finite_difference", "idempotency",
                            "repeatability", "structured_errors", "path_rejection", "folder_discovery", "png_transfer"],
                  "knee": {"run": knee, "repeat_run_id": knee_repeat["run_id"], "csv": knee_rows,
                           "png_bytes": len(knee_pixels), "checks": ["increasing_length", "negative_moment_arms",
                           "finite_difference", "repeatability", "fixed_other_coordinates", "matching_png_pose"]},
                  "forward": forward, "source_search": sources, "v03": v03, "v04": v04, "v05": v05,
                  "scenario_authoring_skill": {"status": "pass", "client_workflow": "create declarative folder, discover, run, check validation artifact; malformed folders quarantined"}}
        print(json.dumps({"transport": label, "status": "pass", "run_id": a["run_id"], "metrics": a["outputs"]["metrics"]}))
        print(json.dumps({"transport": label, "scenario": "knee_sweep", "status": "pass", "run_id": knee["run_id"], "metrics": knee["outputs"]["metrics"]}))
        print(json.dumps({"transport": label, "scenario": "activation_pulse", "status": "pass", "run_id": forward["run"]["run_id"], "metrics": forward["run"]["outputs"]["metrics"]}))
        return result


async def main():
    tag = os.urandom(8).hex()
    result_store = ROOT / "reports/e2e-model-runs" / tag
    result_store.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="hmm-e2e-") as temp:
        test_home = Path(temp)
        for name in ("models", "models.lock.json", "requirements.lock", "runtime-environment.json", "benchmarks", "docs"):
            (test_home / name).symlink_to(ROOT / name)
        (test_home / "results").symlink_to(result_store)
        shutil.copytree(ROOT / "scenarios", test_home / "scenarios")
        new = test_home / "scenarios/external_check"
        shutil.copytree(test_home / "scenarios/elbow_sweep", new)
        manifest = new / "scenario.yaml"
        manifest.write_text(manifest.read_text().replace("id: elbow_sweep", "id: external_check"))
        bad = test_home / "scenarios/broken_check"
        bad.mkdir()
        (bad / "scenario.yaml").write_text("backend: untrusted_shell\ncommand: echo unsafe\n")
        invalid_validation = test_home / "scenarios/bad_validation_check"
        shutil.copytree(test_home / "scenarios/elbow_sweep", invalid_validation)
        path = invalid_validation / "scenario.yaml"
        path.write_text(path.read_text().replace("id: elbow_sweep", "id: bad_validation_check"))
        (invalid_validation / "validation.yaml").write_text("not: [valid")
        bad_sign = test_home / "scenarios/bad_sign_check"
        shutil.copytree(test_home / "scenarios/elbow_sweep", bad_sign)
        path = bad_sign / "scenario.yaml"
        path.write_text(path.read_text().replace("id: elbow_sweep", "id: bad_sign_check"))
        path = bad_sign / "validation.yaml"
        path.write_text(path.read_text().replace("path_length_change: negative", "path_length_change: positive"))
        env = {**os.environ, "HUMAN_MODELS_HOME": str(test_home)}
        stdio = await exercise(StdioServerParameters(command=sys.executable,
            args=["-m", "human_models_mcp"], env=env), "stdio-" + tag)
        log = (ROOT / "reports/logs/http-server.log").open("w")
        server = subprocess.Popen([sys.executable, "-m", "human_models_mcp", "--transport", "http"],
                                  env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("HTTP server exited; see http-server.log")
                try:
                    with socket.create_connection(("127.0.0.1", 8765), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError("HTTP startup timed out")
            import urllib.request
            import urllib.error
            request = urllib.request.Request("http://127.0.0.1:8765/mcp", data=b"{}",
                headers={"Origin": "https://untrusted.invalid", "Content-Type": "application/json"})
            try:
                urllib.request.urlopen(request, timeout=3)
                raise AssertionError("untrusted Origin accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            http = await exercise("http://127.0.0.1:8765/mcp", "http-" + tag)
        finally:
            server.terminate()
            server.wait(timeout=10)
            log.close()
    evidence = {"status": "pass", "offline": "container network_mode=none; loopback only", "stdio": stdio, "http": http,
                "result_store": str(result_store.relative_to(ROOT))}
    (ROOT / "reports/e2e.json").write_text(json.dumps(evidence, indent=2) + "\n")
    lines = ["# Real MCP E2E evidence", "", "Command: `make e2e` (Docker, `network_mode: none`).",
             "", "Persisted isolated result store: `" + evidence["result_store"] + "` (relative to the project).",
             "", "Official SDK v2 clients perform initialize/discovery, tool calls and artifact transfer on stdio and loopback Streamable HTTP.",
             "", "The first run below is the unmodified tool result. Scientific status is numerical sanity only.", "",
             "```json", json.dumps(stdio["run"], indent=2), "```", "", "CSV received through MCP:", "", "```csv"]
    lines.extend([",".join(stdio["csv"][0]), *[",".join(row.values()) for row in stdio["csv"]], "```", "",
                  f"HTTP run: `{http['run']['run_id']}`. Protocol: `{http['protocol']}`.",
                  "Repeat comparison passed at absolute tolerance 1e-12. All artifact hashes verified; PNG decoded with Pillow, nonuniform pixels, pose metadata matched CSV sample.",
                  "", "Raw structured evidence: `reports/e2e.json`; logs: `reports/logs/e2e.log`, `reports/logs/http-server.log`."])
    lines.extend(["", "## Second experiment: prescribed knee sweep", "",
                  "The same offline real-client checks also ran `knee_sweep` on both transports.",
                  "Default recfem_r path lengths increase and signed partial moment arms are negative.",
                  "Other coordinates, including the coupled knee/patellar coordinates, remain fixed; this is not constrained motion.",
                  "", "Unmodified stdio tool result:", "", "```json", json.dumps(stdio["knee"]["run"], indent=2), "```", "",
                  "CSV received through MCP:", "", "```csv", ",".join(stdio["knee"]["csv"][0]),
                  *[",".join(row.values()) for row in stdio["knee"]["csv"]], "```", "",
                  f"HTTP knee run: `{http['knee']['run']['run_id']}`. Independent repeats passed at 1e-12; full CSV hashes matched."])
    (ROOT / "reports/E2E_EVIDENCE.md").write_text("\n".join(lines) + "\n")
    with (ROOT / "reports/E2E_EVIDENCE.md").open("a") as f:
        f.write("\n## Real forward integration\n\nBoth transports executed 10 mj_step calls, an independent repeat and a zero-excitation control.\n\n```json\n")
        f.write(json.dumps(stdio["forward"], indent=2) + "\n```\n")


if __name__ == "__main__":
    asyncio.run(main())
