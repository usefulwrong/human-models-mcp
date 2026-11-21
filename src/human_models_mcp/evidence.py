"""Read-only, claim-specific evidence for persisted model computations."""

import hashlib
import json
from pathlib import Path

from .results import error, get_artifact, get_run


def code_sha256():
    root = Path(__file__).resolve().parent
    hashed = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        hashed.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return hashed.hexdigest()


def read_json(run, artifact_id):
    if artifact_id not in run.get("artifacts", {}):
        return {}
    artifact = get_artifact(run["run_id"], artifact_id)
    if artifact["status"] != "ok":
        raise ValueError(artifact["error"]["message"])
    return json.loads(artifact["data"])


def evidence_context(run):
    scientific, execution = run["scientific"], run["execution"]
    checks = [dict(check, status=check["status"].upper(), threshold=check.get("threshold"))
              for check in scientific.get("checks", [])]
    return {
        "schema_version": "1.0",
        "run_id": run["run_id"],
        "source_model": run["model"],
        "engine": run["engine"],
        "scenario": {"id": run["scenario_id"], "version": run["scenario_version"], "sha256": run["scenario_sha256"]},
        "code_sha256": execution["environment"].get("code_sha256"),
        "code_git_sha": execution["environment"].get("code_git_sha"),
        "package_version": execution["environment"]["package_version"],
        "parameters": execution["parameters"],
        "control_mode": (execution.get("controller") or {}).get("mode", execution["parameters"].get("control")),
        "computed_status": ("completed" if run["status"] == "computed" or execution.get("numeric_status") == "computed"
                            else "failed" if run["status"] == "failed" else "not_run"),
        "numeric_checks": checks,
        "scope_limitations": scientific["limitations"],
        "known_confounds": scientific["limitations"],
        "sources": scientific["citations"],
    }


def get_evidence(run_id, claim_id=None):
    """Query metric:<name> or artifact:<id>; omit the ID to enumerate evidence."""
    run = get_run(run_id)
    if "scientific" not in run:
        return run
    try:
        context = evidence_context(run)
        summary = read_json(run, "summary.json")
        context["check_thresholds"] = summary.get("thresholds", {})
        context["validation_contract"] = read_json(run, "validation.json")
    except (OSError, ValueError) as exc:
        return error("integrity_error", str(exc))
    context["numeric_checks"] += [
        {"name": name, "status": status, "threshold": None, "thresholds_at": "summary.json#/thresholds"}
        for name, status in run["scientific"].get("acceptance", {}).items() if status in {"PASS", "FAIL"}
    ]
    if not context["numeric_checks"]:
        context["numeric_checks"].append({"name": "execution_checks", "status": "NOT_RUN", "threshold": None})
    checked = (context["computed_status"] == "completed"
               and any(x["status"] == "PASS" for x in context["numeric_checks"])
               and all(x["status"] != "FAIL" for x in context["numeric_checks"]))
    execution = run["execution"]
    time_window = ([0, execution["simulation_time_s"]] if execution.get("simulation_time_s") else None)
    claims = {}
    for metric in run.get("outputs", {}).get("metrics", []):
        name = metric["name"]
        side = metric.get("side")
        if side is None:
            side = next((side for token, side in (("r", "right"), ("l", "left")) if token in name.split("_")), None)
        comparison = {"status": "NOT_AVAILABLE"}
        if run["scenario_id"] == "wrist_benchmark" and name in {"rmse_extension", "rmse_ulnar_deviation"}:
            protocol = run["scientific"]["comparison"]
            comparison = {"status": "COMPARED", "dataset": "Nichols, Bednar and Murray (2016), Table 2",
                          "version": protocol["source"].get("doi"), "procedure": protocol["coordinate_definition"],
                          "metric": name, "usable_observations": 5, "usable_frames": None,
                          "result": metric["value"], "unit": metric["unit"]}
        claims["metric:" + name] = {
            "quantity": name, "value": metric["value"], "unit": metric["unit"], "time_window_s": time_window,
            "side": side, "structure": metric.get("structure", execution["parameters"].get("joint")),
            "anatomical_mapping_status": "native", "reference_comparison": comparison,
            "evidence_class": ("compared_with_external_data" if comparison["status"] == "COMPARED" else
                               "internally_checked" if checked else "computed_only"),
            "validation_status": "unvalidated",
            "confidence_explanation": "The run checks describe model execution. Any cited comparison applies only to its named observable.",
        }
    for name, meta in run.get("artifacts", {}).items():
        claims["artifact:" + name] = {
            "quantity": "persisted_artifact", "value": meta, "unit": None, "time_window_s": None,
            "side": None, "structure": None, "anatomical_mapping_status": "unavailable",
            "reference_comparison": {"status": "NOT_AVAILABLE"}, "evidence_class": "computed_only",
            "validation_status": "unvalidated",
            "confidence_explanation": "Manifest digest identifies the persisted file. Retrieve through verified artifact access.",
        }
    if claim_id is not None and claim_id not in claims:
        return error("unsupported", "No evidence for the requested claim. Use a listed metric or artifact ID.")
    selected = claims if claim_id is None else {claim_id: claims[claim_id]}
    return {**context, "claims": [dict(claim, claim_id=key) for key, claim in selected.items()]}
