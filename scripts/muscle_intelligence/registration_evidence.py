"""Install a SHA-pinned, read-only pilot evidence receipt."""

from functools import lru_cache
import json
from pathlib import Path

from anatomy_lab import canonical, digest, read_bounded

LEGACY_SCHEMA = "hmm.reference-registration/1"
SCHEMA = "hmm.reference-registration/2"
CLAIMS = {
    "source_provenance": {"PINNED", "NOT_VERIFIED"},
    "geometry_fit": {"CANDIDATE", "MEASURED", "INCONCLUSIVE", "NOT_RUN"},
    "expert_review": {"PENDING", "DOCUMENTED"},
    "attachment_footprint": {"NOT_VERIFIED", "INDEPENDENT_EVIDENCE"},
    "human_physiology": {"NOT_VALIDATED", "INDEPENDENT_EVIDENCE"},
}
FRAME = "mujoco_world_m"
MAX_REPORT = 4 << 20
MAX_REPLY = 192 << 10


@lru_cache(maxsize=2)
def load_evidence(path, sha):
    raw = read_bounded(Path(path), MAX_REPORT)
    if digest(raw) != sha:
        raise ValueError("registration evidence SHA-256 differs")
    report = json.loads(raw)
    version = report.get("schema_version")
    if version == LEGACY_SCHEMA and report.get("anatomical_registration") == "NOT_VERIFIED":
        return report
    claims = report.get("claims")
    if (version != SCHEMA or not isinstance(claims, dict) or claims.keys() != CLAIMS.keys()
            or any(not isinstance(claims[key], str) or claims[key] not in values
                   for key, values in CLAIMS.items())
            or report.get("anatomical_registration") not in ("NOT_VERIFIED", "VERIFIED")
            or (report["anatomical_registration"] == "VERIFIED" and
                (claims["expert_review"] != "DOCUMENTED" or claims["geometry_fit"] != "MEASURED"
                 or claims["source_provenance"] != "PINNED"
                 or report.get("independent_landmarks", {}).get("count", 0) < 4))):
        raise ValueError("unsupported registration evidence receipt")
    return report


def at_frame(report, sha, base, frame, names, node):
    pins = ("run_id", "motion_sha256", "mapping_revision_sha256", "source_result_sha256",
            "source_model_sha256", "anatomy_revision")
    if any(report[k] != base[k] for k in pins):
        raise ValueError("registration evidence binds to a different source")
    index = frame["state_index"]
    if report["frames"][index] != frame:
        raise ValueError("registration evidence binds to a different saved state")
    pilot = report["pilots"].get(node)
    if not pilot and names:
        pilot = next((p for p in report["pilots"].values() if p["native_route"] == names[0]), None)
    if not pilot:
        return {"status": "OUT_OF_SCOPE", "revision_sha256": sha}
    routes = []
    for name in names:
        route = report["routes"].get(name)
        if route is not None:
            sample = route["samples"][index]
            if sample["state_index"] != index or sample["time_s"] != frame["frame_time"]:
                raise ValueError("registration evidence route clock differs")
            routes.append({"name": name, "status": "MODEL_INTERNAL", **sample})
    bones = [report["bones"][name] for name in pilot["bones"]]
    result = {"status": "NOT_VERIFIED", "revision_sha256": sha, "frame": frame,
              "route_frame": FRAME, "pilot": pilot, "routes": routes, "bones": bones,
              "sources": report["sources"], "blockers": report["blockers"]}
    if report["schema_version"] == SCHEMA:
        result["schema_version"] = SCHEMA
        result["claims"] = report["claims"]
        result["pair_review_summary"] = report["independent_landmarks"]
    if len(canonical(result)) > MAX_REPLY:
        raise ValueError("registration evidence exceeds the per-selection limit")
    return result
