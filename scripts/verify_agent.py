"""Verify retained real-LLM tool evidence for the unchanged scientific runtime."""

import hashlib
import json
from pathlib import Path

from release_check import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "reports/V05_AGENT_EVIDENCE.json"
    if not path.is_file():
        raise RuntimeError("Real LLM evidence is absent; SDK regression clients cannot substitute for it")
    evidence = json.loads(path.read_text())
    assert evidence["kind"] == "separate_llm_agent_with_official_sdk_mcp_bridge"
    assert evidence["source_sha256"] == source_fingerprint(ROOT), "agent evidence belongs to different runtime source"
    assert evidence["review"]["status"] == "pass" and evidence["review"]["unsupported_without_invented_numbers"]
    assert evidence["review"]["distinguishes_comparison_from_validation"]
    assert 10 <= len(evidence["receipts"]) <= 256
    receipts = []
    for item in evidence["receipts"]:
        p = (ROOT / item["path"]).resolve()
        assert p.is_relative_to(ROOT) and p.stat().st_size <= 8 * 1024 * 1024
        data = p.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        receipts.append(json.loads(data))
    tools = {r["tool"] for r in receipts}
    assert {"list_models", "describe_model", "get_model_capabilities", "list_scenarios", "describe_scenario", "run_scenario", "get_result", "get_artifact", "search_sources"} <= tools
    runs = [r["result"] for r in receipts if r["tool"] == "run_scenario" and r["result"].get("status") == "computed"]
    assert {"standing_contact_probe", "assisted_stance"} <= {r["scenario_id"] for r in runs}
    assert all(r["execution"]["environment"]["package_version"] == "0.5.0" for r in runs)
    for case in ("pushup", "running", "breathing", "defecation", "sex_specific_anatomy", "extreme_pose_safety", "standing_balance"):
        aliases = {case}
        aliases |= {"standing_and_breathing"} if case == "breathing" else set()
        aliases |= {"medical_safety"} if case == "extreme_pose_safety" else set()
        aliases |= {"sex_customization"} if case == "sex_specific_anatomy" else set()
        assert any(r["result"].get("status") == "unsupported" and
                   (r["arguments"].get("quantity") in aliases or r["arguments"].get("scenario_id") in aliases) for r in receipts), case
    assert evidence["review"]["distinguishes_assistance_from_balance"]
    for name in ("prompt", "answer", "viewed_png", "named_result_page"):
        p = (ROOT / evidence[name]["path"]).resolve()
        assert p.is_relative_to(ROOT) and hashlib.sha256(p.read_bytes()).hexdigest() == evidence[name]["sha256"]
    print(json.dumps({"status": "pass", "real_llm_session": evidence["session"], "receipt_count": len(receipts),
                      "source_sha256": evidence["source_sha256"], "execution": "verification of retained actual LLM interaction; no new LLM session launched by this command"}, indent=2))


if __name__ == "__main__":
    main()
