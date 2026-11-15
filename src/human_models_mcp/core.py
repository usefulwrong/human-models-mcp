"""Serialized, bounded execution and persistent scientific provenance."""

import fcntl
import hashlib
import json
import mimetypes
import os
import platform
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from . import __version__
from .catalog import MODEL_FILES, CITATIONS, LIMITATIONS, SWEEP_LIMITATIONS, FORWARD_LIMITATIONS, COUPLED_LIMITATIONS, model_card
from .registry import PARAMETER_TYPES, discover, home
from .results import error, get_run, run_dir, store, interrupt_run


@contextmanager
def executor_lock():
    store().mkdir(parents=True, exist_ok=True)
    with (store() / ".executor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def worker(request: dict) -> dict:
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "HMM_PARENT_PID": str(os.getpid())}
    try:
        p = subprocess.run([sys.executable, "-m", "human_models_mcp.worker"],
                           input=json.dumps(request), capture_output=True, text=True, timeout=90, env=env)
        if p.returncode:
            return error("failed", f"engine worker exited {p.returncode}: {p.stderr[-1000:]}")
        return json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        return error("failed", "engine worker exceeded 90 s wall-clock limit")
    except (OSError, ValueError) as exc:
        return error("failed", str(exc)[:500])


def get_joint_info(model_id: str, joint: str | None = None) -> dict:
    if model_id not in MODEL_FILES:
        return error("unsupported", "model has no installed adapter")
    with executor_lock() as acquired:
        if not acquired:
            return error("busy", "one scientific operation at a time; retry later")
        return worker({"operation": "inspect", "joint": joint, "model_id": model_id})


def describe_scenario(scenario_id: str) -> dict:
    return next((x for x in discover()["scenarios"] if x["id"] == scenario_id),
                error("unsupported", "scenario absent or quarantined; use list_scenarios"))


def run_scenario(scenario_id: str, parameters: dict | None = None, idempotency_key: str | None = None) -> dict:
    scenario = describe_scenario(scenario_id)
    if "error" in scenario:
        return scenario
    try:
        parameter_model = PARAMETER_TYPES[scenario["backend"]]
        params = parameter_model.model_validate({**scenario["defaults"], **(parameters or {})}).model_dump()
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
            raise ValueError("idempotency_key must contain 1–128 characters")
    except (ValidationError, ValueError, TypeError) as exc:
        return error("invalid_input", str(exc)[:1500])
    signature = hashlib.sha256(json.dumps({"scenario": scenario, "parameters": params}, sort_keys=True).encode()).hexdigest()
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else None
    with executor_lock() as acquired:
        if not acquired:
            return error("busy", "one scientific operation at a time; retry later")
        runs = list(store().glob("*/manifest.json"))
        for path in runs:
            if not path.is_symlink() and not path.parent.is_symlink():
                try:
                    interrupt_run(path, json.loads(path.read_text()))
                except (OSError, ValueError):
                    continue
        if key_hash:
            for path in runs:
                old = get_run(path.parent.name)
                if old.get("idempotency_key_sha256") == key_hash:
                    if old.get("request_sha256") != signature:
                        return error("invalid_input", "idempotency_key already used with different parameters or manifest")
                    return old
        if len(runs) >= 200 or shutil.disk_usage(store()).free < 128 * 1024 * 1024:
            return error("resource_limit", "store has 200 runs or less than 128 MiB free; owner must archive results")
        card = model_card(verify=True, model_id=scenario["model"])
        if card["status"] != "available":
            return error(card["status"], "model unavailable; provision and verify pinned files and engine")
        run_id = str(uuid4())
        output = run_dir(run_id)
        output.mkdir()
        manifest = {
            "run_id": run_id, "status": "running", "created_at": datetime.now(timezone.utc).isoformat(),
            "scenario_id": scenario_id, "scenario_version": scenario["version"],
            "scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(),
            "request_sha256": signature, "idempotency_key_sha256": key_hash,
            "model": {**{k: card[k] for k in ("id", "source_url", "revision", "asset_sha256", "license")},
                      "integrity": "sha256_verified_for_execution"},
            "engine": card["engine"],
            "execution": {"method": scenario["method"], "physics_backend": "cpu", "render_backend": "none",
                          "seed": None, "parameters": params, "integration_steps": 0,
                          "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                          "package_version": __version__, "machine": platform.machine(),
                                          "requirements_lock_sha256": hashlib.sha256((home() / "requirements.lock").read_bytes()).hexdigest(),
                                          "render_requested": os.environ.get("MUJOCO_GL", "osmesa")},
                          "result_status": "running"},
            "outputs": {"metrics": [], "time_series": [], "images": []},
            "scientific": {"scope": scenario["scope"], "validation_level": "unvalidated",
                           "limitations": LIMITATIONS + (SWEEP_LIMITATIONS if scenario["backend"] == "joint_sweep" else FORWARD_LIMITATIONS), "citations": card["citations"]},
            "artifacts": {},
        }
        if scenario["model"] == "ms_human_700_locomotion":
            manifest["model"]["source_files"] = card["source_files"]
            manifest["scientific"]["limitations"] = card["limitations"]
        manifest_path = output / "manifest.json"
        if params.get("coordinate_mode") == "coupled_knee":
            manifest["scientific"]["limitations"] = LIMITATIONS + COUPLED_LIMITATIONS
        environment_file = home() / "runtime-environment.json"
        if environment_file.is_file():
            shutil.copyfile(environment_file, output / "environment.json")
            manifest["execution"]["environment"]["runtime_environment_sha256"] = hashlib.sha256(environment_file.read_bytes()).hexdigest()

        def save():
            temp = output / "manifest.tmp"
            temp.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
            temp.replace(manifest_path)

        save()
        try:
            (output / "validation.json").write_text(json.dumps(scenario["validation"], indent=2))
            manifest["scientific"]["validation_contract_sha256"] = hashlib.sha256((output / "validation.json").read_bytes()).hexdigest()
            result = worker({"operation": scenario["backend"], "parameters": params, "run_id": run_id,
                             "validation": scenario["validation"], "defaults": scenario["defaults"], "model_id": scenario["model"]})
            manifest["status"] = result["status"]
            manifest["execution"]["result_status"] = result["status"]
            if result["status"] == "computed":
                manifest["scientific"]["validation_level"] = "numerical_sanity"
                manifest["scientific"]["checks"] = result.get("checks", [])
                manifest["outputs"]["metrics"] = result["metrics"]
                manifest["outputs"]["time_series"] = [{"artifact_id": "series.csv", "axis": "sample (not time)",
                    "units": {"sample": "1", "angle_rad": "rad", "length_m": "m", "moment_arm_m": "m",
                              "finite_difference_m_per_rad": "m/rad", "jacobian_error_m_per_rad": "m/rad"},
                    "definition": "moment_arm_m = -partial L / partial q; other coordinates fixed"}]
                if scenario["method"] == "static_pose":
                    manifest["execution"]["coordinate_mode"] = result.get("coordinate_mode", "fixed")
                    if params.get("coordinate_mode") == "coupled_knee":
                        manifest["outputs"]["time_series"][0]["definition"] = "moment_arm_m = -dL/dq along the selected knee's eight source equality polynomials"
                        manifest["outputs"]["time_series"][0]["units"].update({"translation_residual_m": "m", "rotation_residual_rad": "rad",
                            "translation_tangent_error_m_per_rad": "m/rad", "rotation_tangent_error_rad_per_rad": "rad/rad"})
                if scenario["method"] == "dynamic_forward":
                    manifest["outputs"]["time_series"] = [result["time_series"]]
                    manifest["execution"]["integration_steps"] = result["integration_steps"]
                    manifest["execution"]["simulation_time_s"] = result["simulation_time_s"]
                    manifest["execution"]["integrator"] = result["integrator"]
                    manifest["execution"]["initial_conditions"] = result["initial_conditions"]
                manifest["render"] = result["render"]
                manifest["execution"]["render_backend"] = result["render"]["render_backend"]
                manifest["execution"]["timestep_s"] = result["timestep_s"]
                manifest["counts"] = result["counts"]
                if "model_derivation" in result:
                    manifest["model"]["derivation"] = result["model_derivation"]
                    manifest["scientific"]["limitations"] = card["limitations"] + result["limitations"]
                    if "controller" in result:
                        manifest["execution"]["controller"] = result["controller"]
                if "scientific_comparison" in result:
                    manifest["scientific"]["comparison"] = result["scientific_comparison"]
                    manifest["scientific"]["limitations"] = LIMITATIONS + result["scientific_comparison"]["limitations"]
                    manifest["scientific"]["citations"] = CITATIONS + result["citations"]
                if "time_series" in result:
                    manifest["outputs"]["time_series"] = [result["time_series"]]
                if "acceptance" in result:
                    manifest["scientific"]["acceptance"] = result["acceptance"]
                    manifest["outputs"]["muscles"] = result["muscle_outputs"]
                    manifest["scientific"]["citations"] += result["citations"]
                if "contact_outputs" in result:
                    manifest["outputs"]["contacts"] = result["contact_outputs"]
                    manifest["scientific"]["numerical_status"] = "validated_for_named_checks"
                    if result.get("acceptance", {}).get("numerical_bounds") == "FAIL":
                        manifest["scientific"]["numerical_status"] = "failed_named_bounds"
                    manifest["scientific"]["validation_scope"] = "Only the executable checks named in this run; no human experimental or clinical validation."
                if result["render"]["status"] == "rendered":
                    manifest["outputs"]["images"] = [{"artifact_id": "pose.png", "metadata": "frame.json"}]
                    for name in ("plots.png", "overview.png", "animation.gif"):
                        if (output / name).is_file():
                            manifest["outputs"]["images"].append({"artifact_id": name, "metadata": "frames.json" if (output / "frames.json").is_file() else "frame.json"})
                elif params.get("render"):
                    manifest["status"] = manifest["execution"]["result_status"] = "failed"
                    manifest["execution"]["numeric_status"] = "computed"
                    manifest["error"] = {"code": "render_failed", "message": result["render"].get("message", "Requested rendering did not complete")}
            else:
                manifest["error"] = result.get("error", {"code": result["status"], "message": "engine unavailable"})
                manifest["scientific"]["validation_level"] = "unvalidated"
            (output / "bibliography.json").write_text(json.dumps(manifest["scientific"]["citations"], indent=2))
            for path in sorted(output.iterdir()):
                name = path.name
                if name in ("manifest.json", "manifest.tmp"):
                    continue
                if path.is_file() and not path.is_symlink():
                    if path.stat().st_size > 2 * 1024 * 1024:
                        raise ValueError("artifact exceeds 2 MiB: " + name)
                    manifest["artifacts"][name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "bytes": path.stat().st_size, "mime_type": mimetypes.guess_type(name)[0] or "application/octet-stream"}
        except Exception as exc:
            manifest["status"] = manifest["execution"]["result_status"] = "failed"
            manifest["scientific"]["validation_level"] = "unvalidated"
            manifest["error"] = {"code": "execution_error", "message": str(exc)[:1000]}
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        save()
        return manifest
