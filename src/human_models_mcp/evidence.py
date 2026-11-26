"""Read-only, claim-specific evidence for persisted model computations."""

import hashlib
import json
import math
from pathlib import Path

from .results import error, get_artifact, get_run
from .scientific_quantity import CONTACT, DERIVED, MUSCLE, PUSHUP_METRICS, quantity, scientific_quantity, sources


def code_sha256():
    root = Path(__file__).resolve().parent
    hashed = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        hashed.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return hashed.hexdigest()


def read_json(run, artifact_id):
    if artifact_id not in run.get("artifacts", {}):
        return {}
    artifact = get_artifact(run["run_id"], artifact_id)
    if artifact["status"] != "ok":
        raise ValueError(artifact["error"]["message"])
    return json.loads(artifact["data"])


def evidence_context(run, summary=None, validation=None):
    scientific, execution = run["scientific"], run["execution"]
    acceptance = scientific.get("acceptance", {})
    thresholds = (summary or {}).get("thresholds", {})
    checks = [dict(check, status=check["status"].upper(), threshold=check.get("threshold"))
              for check in scientific.get("checks", [])]
    checks += [
        {"name": name, "status": status, "threshold": None,
         "thresholds_at": "summary.json#/thresholds" if thresholds else None}
        for name, status in acceptance.items() if status in {"PASS", "FAIL", "NOT_RUN"}
    ]
    if not checks:
        checks.append({"name": "execution_checks", "status": "NOT_RUN", "threshold": None})
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
        "acceptance": acceptance,
        "check_thresholds": thresholds,
        "validation_contract": validation or {},
        "human_validation_status": acceptance.get("human_experimental_validation", "NOT_VALIDATED"),
        "human_safety_status": "unsupported",
        "scope_limitations": scientific["limitations"],
        "known_confounds": scientific["limitations"],
        "sources": scientific["citations"],
    }


def get_evidence(run_id, claim_id=None):
    """Query metric:<name> or artifact:<id>; omit the ID to enumerate evidence."""
    run = get_run(run_id)
    if "error" in run:
        return run
    try:
        metrics = run.get("outputs", {}).get("metrics", [])
        if any(not math.isfinite(metric["value"]) for metric in metrics):
            raise ValueError("run manifest contains a nonfinite metric")
        context = evidence_context(run, read_json(run, "summary.json"), read_json(run, "validation.json"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return error("integrity_error", str(exc))
    checked = (context["computed_status"] == "completed"
               and all(x["status"] == "PASS" for x in context["numeric_checks"]))
    execution = run["execution"]
    time_window = ([0, execution["simulation_time_s"]] if execution.get("simulation_time_s") else None)
    claims = {}
    metric_definitions = {}
    for metric in metrics:
        name = metric["name"]
        if metric.get("definition"):
            metric_definitions[name] = metric["definition"]
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
    for name, status in context["acceptance"].items():
        claims["gate:" + name] = {
            "quantity": name, "value": status, "unit": None, "time_window_s": time_window,
            "side": None, "structure": None, "anatomical_mapping_status": "unavailable",
            "reference_comparison": {"status": "NOT_AVAILABLE"},
            "evidence_class": "internally_checked" if status in {"PASS", "FAIL", "NOT_ACHIEVED"} else "computed_only",
            "validation_status": "unvalidated",
            "confidence_explanation": "This status applies to the named scenario criterion under the recorded controls.",
        }
    catalog = {}
    names = run.get("outputs", {}).get("muscles", {}).get("chunks", [])
    if names:
        catalog.update(MUSCLE)
    if "contact_manifest.json" in run.get("artifacts", {}):
        catalog.update(CONTACT)
    for name, definition in catalog.items():
        claims["quantity:" + name] = {
            "quantity": name, "unit": definition["unit"], "value": None, "time_window_s": time_window,
            "definition": definition["definition"], "reference_comparison": {"status": "NOT_AVAILABLE"},
            "evidence_class": "quantity_definition", "validation_status": "unvalidated",
        }
    if claim_id is not None and claim_id not in claims:
        return error("unsupported", "No evidence for the requested claim. Use a listed metric, gate, quantity or artifact ID.")
    selected = claims if claim_id is None else {claim_id: claims[claim_id]}
    definitions, files = {}, {}
    comparison = None
    for key, claim in selected.items():
        kind, name = key.split(":", 1)
        if kind == "quantity":
            definitions[key] = {**catalog[name], "quantity_id": name}
            if name in ("overlay", "display_surface"):
                definitions[key]["scope"] = "installed_motion_scene"
            if name in MUSCLE:
                files.update(sources(run, "trajectory.npz", "trajectory_metadata.json", "actuators.json",
                                     *names, "muscle_ranking.json"))
            else:
                files.update(sources(run, "contact_manifest.json", "contact_surfaces.json", "contacts.json"))
        elif kind == "metric":
            pushup_definition = PUSHUP_METRICS.get(name) if run["scenario_id"].startswith("pushup") else None
            definition = metric_definitions.get(name) or pushup_definition
            definitions[key] = quantity(claim["unit"], definition or
                                        "Run metric as emitted by the scenario. See its method and validation contract.",
                                        DERIVED if pushup_definition else None)
            definitions[key].update(quantity_id=name, definition_status="AVAILABLE" if definition else "NOT_AVAILABLE")
            files.update(sources(run, "summary.json", "validation.json", "series.csv"))
            if claim_id is not None and claim["reference_comparison"]["status"] == "COMPARED":
                comparison = claim["reference_comparison"]
        elif kind == "artifact":
            files.update(sources(run, name))
        else:
            files.update(sources(run, "summary.json", "validation.json"))
    return {**context, "claims": [dict(claim, claim_id=key) for key, claim in selected.items()],
            "scientific_quantity": scientific_quantity(
                run, definitions, files=files, window={"simulation_time_s": time_window, "sampling": "run_scope"},
                comparison=comparison, uncertainty=context["scope_limitations"])}
