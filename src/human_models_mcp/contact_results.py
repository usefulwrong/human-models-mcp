"""Read verified, manifest-listed contact measurements at saved states."""

import base64
import hashlib
from io import BytesIO
import json
import math
from zipfile import BadZipFile

import numpy as np

from .results import error, get_artifact, get_run
from .scene_export import safe_archive
from .scientific_quantity import CONTACT, DERIVED, PUSHUP_SUMMARY, quantity as quantity_definition
from .scientific_quantity import scientific_quantity, sources


def get_contact(run_id, part, sample=None, time_s=None, quantity="contact"):
    if quantity != "contact":
        result = {**error("unsupported", "only native contact wrench and mapped surface distances are available"),
                  "measurement_status": "UNSUPPORTED"}
        if quantity == "skin_contact_pressure":
            result.update(data_status="NOT_MODELED", quantity_definition=CONTACT[quantity])
        return result
    if ((sample is None) == (time_s is None) or sample is not None and type(sample) is not int
            or time_s is not None and (type(time_s) not in (int, float) or not math.isfinite(time_s))):
        return error("invalid_input", "provide exactly one saved sample index or time in seconds")
    run = get_run(run_id)
    if "error" in run:
        return run
    if "contact_manifest.json" not in run.get("artifacts", {}):
        return {**error("unsupported", "run lacks the experimental contact manifest"),
                "measurement_status": "UNSUPPORTED"}

    def verified(name):
        result = get_artifact(run_id, name)
        if "error" in result:
            raise ValueError(result["error"]["message"])
        expected = sources(run, name)
        if expected and result["sha256"] != expected[name]:
            raise ValueError("run artifact binding changed")
        return result["data"]

    def load(name):
        data = json.loads(verified(name))
        # Reject Python's permissive JSON constants before returning scientific data.
        json.dumps(data, allow_nan=False)
        return data

    try:
        manifest = load("contact_manifest.json")
        frames = load(manifest["surface_samples"])["frames"]
        if sample is None:
            sample = next((i for i, frame in enumerate(frames) if abs(frame["time_s"] - time_s) <= 1e-9), -1)
        if not 0 <= sample < len(frames):
            return error("invalid_input", "requested saved sample does not exist")
        selected = frames[sample]
        if state_file := manifest.get("states"):
            raw = BytesIO(base64.b64decode(verified(state_file), validate=True))
            safe_archive(raw)
            raw.seek(0)
            with np.load(raw, allow_pickle=False) as saved:
                clock, states = saved["time_s"], saved["states"]
                if (clock.shape != (len(frames),) or states.ndim != 2 or len(states) != len(frames)
                        or not np.isfinite(states[sample]).all()
                        or clock[sample] != selected["time_s"]
                        or hashlib.sha256(states[sample].tobytes()).hexdigest() != selected["state_sha256"]):
                    raise ValueError("contact receipt differs from the saved trajectory")
        elif "trajectory.npz" in run["artifacts"]:
            raise ValueError("contact manifest has no saved trajectory binding")
        rows = manifest["visible_surfaces"]
        keys = [key for key, row in rows.items()
                if part in (key, row["body"], *row["collision_geoms"])
                or part in ("hand_l", "hand_r") and row["body"].startswith(part + "_")]
        if not keys:
            return error("invalid_input", "part is not in the mapped surface inventory")
        proxies = {manifest["collision_geoms"][geom]["geom_id"] for key in keys for geom in rows[key]["collision_geoms"]}
        event_chunks = load(manifest["events"])["chunks"]
        contacts = []
        for chunk in event_chunks:
            contacts.extend(event for event in load(chunk)["contacts"] if event["sample"] == sample
                            and event["floor_contact"] and proxies.intersection((event["geom0"], event["geom1"])))
        if any("time_s" in event and event["time_s"] != selected["time_s"] for event in contacts):
            raise ValueError("contact event clock differs from saved state")
        if len(contacts) > 256 or len(keys) > 64:
            return error("resource_limit", "select a smaller contact part")
        bound = ("contact_manifest.json", manifest["surface_samples"], manifest["events"], *event_chunks,
                 manifest.get("states", "trajectory.npz"), "summary.json")
        scientific = scientific_quantity(
            {"run_id": run_id, **run}, CONTACT, files=sources(run, *bound),
            window={"state_index": sample, "time_s": selected["time_s"],
                    "state_sha256": selected["state_sha256"], "sampling": "exact_saved_sample"},
            uncertainty=("Collision proxy geometry and selected floor coverage.", "Friction and compliance assumptions.",
                         "External assistance and lack of independent force or pressure measurements."))
        scientific["contact_identity"] = {"part": part, "profile": manifest.get("profile"), "world": manifest["world"],
                                          "origin": "native_mujoco_floor_proxy_pairs"}
        scientific["independent_check"] = ("Compare force plate reactions using matched support and timing. "
                                           "Validate skin pressure separately with a pressure measurement protocol.")
        metrics = {row["name"]: row for row in run.get("outputs", {}).get("metrics", [])}
        diagnostics = {}
        if "summary.json" in run.get("artifacts", {}):
            summary = load("summary.json")["metrics"]
            for key, definition in PUSHUP_SUMMARY.items():
                if key in metrics:
                    value = summary[key]
                    if value != metrics[key]["value"]:
                        raise ValueError("run manifest and summary metric differ")
                    metadata = quantity_definition(metrics[key]["unit"], definition, DERIVED)
                    diagnostics[key] = {"value": value, **metadata, "sampling": "run_scope", "source": "summary.json"}
        bearing = any(event["normal_force_N"] > 1e-6 for event in contacts)
        return {"status": "ok", "measurement_status": "LOAD_BEARING" if bearing else
                "CONTACT_CANDIDATE" if contacts else "NO_CONTACT",
                "run_id": run_id, "sample": sample, "time_s": selected["time_s"],
                "state_sha256": selected["state_sha256"], "world": manifest["world"], "floor": manifest["floor"],
                "scientific_quantity": scientific, "scenario_diagnostics": diagnostics,
                "total_normal_force_N": math.fsum(event["normal_force_N"] for event in contacts),
                "skin_contact_pressure": {"status": "NOT_MODELED", "value": None, "unit": "Pa"},
                "surfaces": {key: {**rows[key], "signed_distance_m": selected["surfaces"][key][0],
                                  "vertex_world_m": selected["surfaces"][key][1]} for key in keys},
                "contacts": contacts}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, EOFError, BadZipFile) as exc:
        return error("integrity_error", str(exc)[:500])
