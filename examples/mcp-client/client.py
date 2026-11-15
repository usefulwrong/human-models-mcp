"""Fresh external client: uses only the public MCP protocol and the agent skills."""

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="optional Streamable HTTP endpoint")
    parser.add_argument("--docker", action="store_true", help="launch the documented Docker Compose stdio connector")
    parser.add_argument("--compose", type=Path, help="trusted operator's offline bundle Compose file")
    parser.add_argument("--scenario", default="elbow_sweep")
    parser.add_argument("--output", default="reports/fresh-client.json")
    parser.add_argument("--save-dir", type=Path, help="new directory for all verified result files and an offline index.html")
    args = parser.parse_args()
    if args.docker or args.compose:
        compose = args.compose.resolve() if args.compose else Path(__file__).resolve().parents[2] / "compose.yaml"
        root = compose.parent
        source = StdioServerParameters(command="docker", args=["compose", "-f", str(compose),
            "-p", os.environ.get("COMPOSE_PROJECT_NAME", "human-models-mcp-night"), "run", "--rm", "--no-deps", "-T", "runtime"], cwd=str(root),
            env={key: os.environ[key] for key in ("HMM_RESULTS_DIR", "HMM_RUNTIME_IMAGE", "HMM_RENDER_IMAGE", "COMPOSE_PROJECT_NAME", "HMM_UID", "HMM_GID") if key in os.environ})
    else:
        source = args.url or StdioServerParameters(command=sys.executable,
            args=["-m", "human_models_mcp"], env=dict(os.environ))
    async with Client(source, read_timeout_seconds=120) as client:
        tools = [t.name for t in (await client.list_tools()).tools]

        async def call(name, params=None):
            result = await client.call_tool(name, params or {})
            if result.is_error:
                raise RuntimeError(str(result.content))
            return result.structured_content

        models = await call("list_models")
        scenarios = await call("list_scenarios")
        scenario = await call("describe_scenario", {"scenario_id": args.scenario})
        assert scenario["id"] in [s["id"] for s in scenarios["scenarios"]]
        card = await call("describe_model", {"model_id": scenario["model"]})
        assert card["id"] in [m["id"] for m in models["models"]]
        contact = scenario["backend"] in ("standing_contact_probe", "assisted_stance")
        for capability in scenario["required_capabilities"]:
            supported = await call("get_model_capabilities", {"model_id": card["id"], "quantity": capability})
            assert supported["status"] == "available" and capability in supported["capabilities"]
        assert (await call("get_model_capabilities", {"model_id": card["id"], "quantity": "medical_safety"}))["status"] == "unsupported"
        term = scenario["defaults"].get("muscle", scenario["id"])
        terminology = await call("search_sources", {"query": term})
        assert terminology["status"] == "ok" and terminology["model_revision"] == card["revision"]
        assert any(m["id"] == term for m in terminology["matches"])
        run = await call("run_scenario", {"scenario_id": scenario["id"], "parameters": {}})
        assert run["status"] == "computed", run
        if scenario["backend"] == "pushup":
            assert (await call("get_result", {"run_id": run["run_id"]})) == run
            summary = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "summary.json"})
            assert hashlib.sha256(summary["data"].encode()).hexdigest() == summary["sha256"]
            assert json.loads(summary["data"])["acceptance"] == run["scientific"]["acceptance"]
            evidence = {"run": run, "tools": tools, "source_search": terminology,
                        "interpretation": "Read separate acceptance gates, mechanical pad/damping recipe and all-actuator data; activation is not EMG."}
            if args.save_dir:
                from artifacts import export_run
                evidence["export"] = str(await export_run(call, run, args.save_dir))
                print("Open result: " + evidence["export"])
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps({"status": "computed", "run_id": run["run_id"], "acceptance": run["scientific"]["acceptance"]}))
            return
        assert run["scientific"]["validation_level"] == "numerical_sanity"
        persisted = await call("get_result", {"run_id": run["run_id"]})
        assert persisted == run
        contract = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "validation.json"})
        assert hashlib.sha256(contract["data"].encode()).hexdigest() == run["scientific"]["validation_contract_sha256"]
        assert all(check["status"] == "pass" for check in run["scientific"]["checks"])
        artifact = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "series.csv"})
        assert hashlib.sha256(artifact["data"].encode()).hexdigest() == artifact["sha256"]
        rows = list(csv.DictReader(io.StringIO(artifact["data"])))
        dynamic = run["execution"]["method"] == "dynamic_forward"
        assert len(rows) == (scenario["defaults"]["steps"] + 1 if dynamic else scenario["defaults"]["samples"])
        if contact:
            rules = scenario["validation"]["checks"]
            assert max(float(r["force_residual_N"]) for r in rows) <= rules["force_balance_tolerance_N"]
            assert max(float(r["moment_residual_Nm"]) for r in rows) <= rules["moment_balance_tolerance_Nm"]
            assert run["scientific"]["numerical_status"] == "validated_for_named_checks"
        else:
            assert all(float(row["length_m"]) > 0 for row in rows)
        if dynamic:
            if not contact:
                assert all(0 <= float(row["activation"]) <= 1 for row in rows)
            assert abs(float(rows[-1]["time_s"]) - run["execution"]["simulation_time_s"]) < 1e-12
            assert run["execution"]["integration_steps"] == scenario["defaults"]["steps"]
        else:
            assert max(float(row["jacobian_error_m_per_rad"]) for row in rows) < 1e-5
            assert run["execution"]["method"] == "static_pose" and run["execution"]["integration_steps"] == 0
        summary = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "summary.json"}))["data"])
        assert summary["metrics"] == run["outputs"]["metrics"]
        image_evidence = None
        if run["outputs"]["images"]:
            from PIL import Image
            image = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "pose.png"})
            binary = base64.b64decode(image["data"])
            assert hashlib.sha256(binary).hexdigest() == image["sha256"]
            picture = Image.open(io.BytesIO(binary))
            picture.verify()
            image_evidence = {"format": picture.format, "size": list(picture.size), "bytes": len(binary)}
            frame = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "frame.json"}))["data"])
            poses = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "poses.json"}))["data"])
            assert frame["qpos"] == poses["qpos"][-1] and frame["model_id"] == card["id"]
            assert frame["sample"] == len(rows) - 1
            assert abs(frame["simulation_time_s"] - (float(rows[-1]["time_s"]) if dynamic else 0)) < 1e-12
        motion = None
        if "trajectory.npz" in run["artifacts"] and run["outputs"]["images"]:
            metadata = json.loads((await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "frames.json"}))["data"])
            animation = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "animation.gif"})
            binary = base64.b64decode(animation["data"])
            assert hashlib.sha256(binary).hexdigest() == animation["sha256"]
            with Image.open(io.BytesIO(binary)) as gif:
                assert gif.n_frames == len(metadata["frames"]) == 21
                gif.seek(gif.n_frames - 1)
                gif.load()
            state_archive = await call("get_artifact", {"run_id": run["run_id"], "artifact_id": "trajectory.npz"})
            assert hashlib.sha256(base64.b64decode(state_archive["data"])).hexdigest() == metadata["state_archive_sha256"]
            motion = {"frames": len(metadata["frames"]), "animation_sha256": animation["sha256"],
                      "saved_states_sha256": metadata["state_archive_sha256"], "camera": metadata["camera"]}
        if not contact:
            start, end = float(rows[0]["length_m"]), float(rows[-1]["length_m"])
        if contact:
            interpretation = (f"Native locomotion foot-floor contact transient for {rows[-1]['time_s']} s: "
                f"GRF_z {rows[-1]['grf_z_N']} N, external pelvis support_z {rows[-1]['assist_force_z_N']} N, "
                f"COM height {rows[-1]['com_z_m']} m. External support is {scenario['defaults']['assistance']}. "
                "Read the source contact map, initialization and solver margins. Named force/momentum checks are numerical; "
                "point-contact hull/CoP inclusion does not establish unassisted balance, tissue collision, human ground reactions or safety.")
        elif "comparison" in run["scientific"]:
            interpretation = ("Descriptive comparison of ten neutral-wrist moment arms with Nichols et al. (2016) Table 2. "
                "Published cadaver means and between-specimen SD are compared with a generic model, using a declared mesh-based coordinate mapping. "
                "No fitting, specimen matching, confidence interval, whole-model experimental validation or clinical safety claim follows. "
                "Read comparison.json for coordinate and posture limitations.")
        elif dynamic:
            conditions = "Model integration with a soft pelvis fixture and prescribed elbow torque" if "derivation" in run["model"] else "Uncontrolled model integration"
            interpretation = (f"{conditions} for {rows[-1]['time_s']} s: "
                f"excitation {rows[-1]['excitation']}, final activation {rows[-1]['activation']} (dimensionless), "
                f"signed actuator force {rows[-1]['actuator_force_N']} N and path length {end:.9f} m. "
                "No posture controller, equilibrium initialization, measured human movement, experimentally validated biological force, "
                "organ function or medical safety was established.")
        else:
            interpretation = (f"In this model, {scenario['defaults']['muscle']} path length is {start:.9f} m "
                f"at {rows[0]['angle_rad']} rad and {end:.9f} m at {rows[-1]['angle_rad']} rad "
                f"(change {end-start:.9f} m). Lengths are in metres; signed moment arms are minus the length gradient "
                + ("along eight local knee equalities. " if run["execution"].get("coordinate_mode") == "coupled_knee" else "with other coordinates fixed. ") +
                "No equilibrium, human motion, muscle force, organ function or medical safety was established.")
        evidence = {"protocol": str(client.protocol_version), "tools": tools, "transport": "http" if args.url else "stdio",
                    "model": {"id": card["id"], "revision": card["revision"]}, "run": run,
                    "csv_rows": rows, "png": image_evidence, "motion": motion,
                    "source_search": terminology,
                    "interpretation": interpretation,
                    "skills_followed": ["skills/human-models-mcp/SKILL.md", "skills/scientific-interpretation/SKILL.md"]}
        if args.save_dir:
            from artifacts import export_run
            viewer = await export_run(call, run, args.save_dir)
            evidence["export_directory"] = str(args.save_dir.resolve())
            evidence["viewer"] = str(viewer)
            print("Open result: " + str(viewer))
        Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"status": "pass", "run_id": run["run_id"], "metrics": run["outputs"]["metrics"],
                          "transport": evidence["transport"], "png": image_evidence}))


if __name__ == "__main__":
    asyncio.run(main())
