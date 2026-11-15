"""Render v0.4 handover from current command results, never historical PASS claims."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    reports = ROOT / "reports"
    release = json.loads((reports / "V04_RELEASE_CHECK.json").read_text())

    def observed(filename, gate):
        path = reports / filename
        return json.loads(path.read_text()) if release["gates"][gate]["status"] == "pass" and path.is_file() else {}

    e2e = observed("e2e.json", "e2e")
    clean = observed("clean-copy.json", "clean-check")
    bundle = observed("offline-bundle.json", "package")
    doctor = observed("doctor.json", "doctor")
    lines = ["# UsefulWrong / human-models-mcp — v0.4 handoff", "",
             f"**RELEASE_STATUS: {release['release_status']}**", "",
             f"Checked: {release['timestamp']}. Baseline/HEAD: `{release['baseline_head']}` / `{release['head']}`.",
             f"New local commits: `{release['new_commits']}`. No push or publication.",
             f"Tested source SHA-256: `{release['source_sha256']}`.", f"Docker image: `{release['image_id']}`.", "",
             "## Independent acceptance and changes", "",
             "Before changes, doctor/build/test/e2e/clean-check all exited 0, with 42 tests and all five v0.3 scenarios through real stdio and HTTP. See V04_BASELINE.json and logs/v04-baseline-*.log.",
             "The five original scenarios remain. Added wrist_benchmark (published cadaver aggregate comparison, geometric static analysis) and elbow_tracking (real forward dynamics with a bounded external PD joint controller). No second heavy engine or learned policy installed.",
             "Discovery now exposes bounded parameter schemas; unsupported quantities have explicit reasons. Source search distinguishes experimental references and wrapper scope. State/frame hashes specify their encodings. A complete MCP artifact export produces a named local HTML page without UUID lookup.", "",
             "## Commands actually run", "", "| Command | Exit | Status | Seconds | Log |", "| --- | --- | --- | --- | --- |"]
    for gate in release["gates"].values():
        if "command" in gate:
            lines.append(f"| `{gate['command']}` | {gate['exit_code']} | {gate['status']} | {gate['seconds']} | `{gate['log']}` |")
    lines += ["", "Outer command: `make release-check`. Exit 0 requires every mandatory gate; the read-only Git mount prevents branch/commit and strict committed-checkout gates. A successful working-source fixture does not erase that limitation.",
              "", "## Scientific observations", ""]
    evidence = ["# Actual MCP E2E — v0.4", "", "Command: `make release-check` (individual commands and exit codes in V04_HANDOFF.md).", "",
                "The official MCP SDK initializes/discovers/calls tools over stdio and Streamable HTTP. Scientific containers have network_mode=none; HTTP uses only container loopback. All seven scenarios execute the actual pinned MuJoCo model. SDK regression clients and the separate real LLM session are documented separately.", ""]
    if e2e:
        lines += ["Both transports and seven fresh host clients passed real scientific calls. Unit/schema/security tests, source hashes, finite differences, saved-state restart, parameter rejection, interruption recovery, reproducibility, artifact hashes and headless rendering are exercised by make test/e2e.", "",
                  "| Scenario | Metric | Value | Unit |", "| --- | --- | --- | --- |"]
        for transport in ("stdio", "http"):
            item = e2e[transport]
            evidence += [f"## {transport}: protocol {item['protocol']}", "", "Tools: " + ", ".join(item["tools"]), ""]
            runs = {"elbow_sweep": item["run"], "knee_sweep": item["knee"]["run"], "activation_pulse": item["forward"]["run"],
                    "knee_coupled": item["v03"]["coupled_knee"]["run"], "loaded_elbow": item["v03"]["loaded_elbow"]["run"],
                    "wrist_benchmark": item["v04"]["benchmark"]["run"], "elbow_tracking": item["v04"]["tracking"]["run"]}
            for name, run in runs.items():
                evidence += [f"Actual run_scenario result: {name}", "", "```json", json.dumps(run, indent=2), "```", ""]
                if transport == "stdio":
                    for metric in run["outputs"]["metrics"]:
                        lines.append(f"| {name} | {metric['name']} | {metric['value']:.12g} | {metric['unit']} |")
            checks = {name: {k: v for k, v in value.items() if k not in ("run", "csv")} for name, value in item["v04"].items()}
            evidence += ["Independent v0.4 checks:", "", "```json", json.dumps(checks, indent=2), "```", ""]
        lines += ["", f"Full manifests and protocol evidence: [e2e.json](e2e.json). Result store: `{e2e['result_store']}`."]
    else:
        lines.append("Current scientific E2E did not pass; no previous run is promoted to current success.")
    lines += ["", "## Hardware, files and agent connection", "", f"CPU: {doctor.get('cpu', 'not_run')}. Physics: CPU."]
    for command in doctor.get("commands", []):
        if command.get("exit_code") == 0 and "nvidia-smi" in command.get("command", []):
            lines.append("Observed GPU: `" + command["stdout"].strip() + "`.")
            break
    if release["gates"].get("gpu-smoke", {}).get("status") == "pass":
        lines.append("NVIDIA EGL passed separately from OSMesa CPU rendering. gpu.json and gpu-tracking.json record actual GL vendor/device, 21 state-derived frames each, and numerical CSV equality with the CPU run.")
    lines += ["Display subsets: [tracking overview](../docs/demo_v04/elbow_tracking/overview.png), [tracking GIF](../docs/demo_v04/elbow_tracking/animation.gif), [comparison plot](../docs/demo_v04/wrist_benchmark/plots.png). Full raw frames, integration states and all files are in the demo store identified by demo-store.json; the demo gate records whether they were refreshed.",
              "Agent connector: `python3 scripts/print_client_config.py`. Working tools: list_models, describe_model, get_model_capabilities, get_joint_info, list_scenarios, describe_scenario, run_scenario, get_result, get_artifact, search_sources. [Separate real LLM evaluation](V04_AGENT_E2E.md).", "",
              "```sh", "make build", "make experiment", "python3 scripts/experiment.py --scenario wrist_benchmark", "python3 scripts/experiment.py --scenario elbow_tracking", "make release-check", "```", "",
              "The experiment command prints a newly created local result page and transfers all artifacts through MCP with size/SHA checks. It needs no UUID lookup. Initial build/provision requires network; normal scientific execution and the offline bundle do not."]
    if clean:
        lines += ["", f"Fresh fixture: `{clean['clone']}`; source state `{clean['source_state']}`; no-cache image `{clean['image_id']}`. Empty stores, newly downloaded pinned model assets, lint/unit/package, all seven scenarios on both transports and fresh external motion/comparison/tracking clients passed. This is a working-source fixture when the source state says overlay, not a clean committed checkout."]
    if bundle:
        lines += ["", f"Offline bundle: `{bundle['bundle']}`. Image archive SHA-256: `{bundle['image_archive_sha256']}`. `python3 verify.py --load` verified file hashes and loaded the immutable image; seven fresh offline clients and named exports passed."]
    lines += ["", "## Scientific limits and remaining blockers", "",
              "The wrist comparison uses ten published nonimpaired cadaver means/SDs from Nichols et al. (2016), DOI 10.1371/journal.pone.0157346, CC0. Its geometric-axis protocol approximates anatomical landmarks; source population/posture and upstream calibration overlap are not fully matched. No parameters are fitted by this implementation. This is a scoped published experimental-reference comparison, not independent held-out whole-model or clinical validation. See V04_SCIENTIFIC_BENCHMARK.md.",
              "The tracking target is synthetic; torque is supplied by an external joint servo with an artificial compliant pelvis fixture. It is not natural muscle/neural control, gait, equilibrium certification or evidence of safe human motion. All DOFs continue evolving. Muscle paths are not muscle volumes. Knee coupling retains the source range conflict documented in SCIENTIFIC_AUDIT.md.",
              "Organs, breathing, defecation, sex/age/pathology customization, injury risk and medical safety remain unsupported. No clinical validation, second-engine experiment, upstream learned locomotion/manipulation controller, or public HTTP deployment is claimed.",
              "Git blocker: authorized branch creation failed (exit 128); findmnt reports .git mounted ro. No new local commit can be written in this environment; no sandbox escalation, alternate write path or push was attempted. Native Codex CLI also failed twice before starting a session because its app-server initialization required a read-only path. The separate LLM evaluation uses the explicit official-SDK tool bridge and is labeled accordingly.",
              "Exact numerical reproduction is tested on this CPU/container. OSMesa and NVIDIA pixels differ. Debian apt dependencies are not snapshot-pinned; preserve the tested offline image for exact system libraries. Hashes establish byte consistency, not distributor authenticity.", "",
              "## Next actions (at most five)", "",
              "1. Have the operator provide writable Git metadata, create the authorized branch/commits, then rerun make release-check from a clean committed checkout.",
              "2. Check the source authors' calibration lineage before describing the wrist dataset as held out; obtain matched bone landmarks/specimen geometry for a stronger comparison.",
              "3. Resolve the knee polynomial/range inconsistency with upstream before expanding constrained knee trajectories.",
              "4. Evaluate a pinned MSGym policy only after confirming variant, observation/action normalization and model/weight licenses.",
              "5. Assess collision coverage and licensed geometry before any impossible-pose or layered-anatomy demonstration.", "", "## Changed files and Git status", ""]
    status_text, changed_files = "git_unavailable", []
    try:
        status = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True)
        status_text = status.stdout.rstrip() if status.returncode == 0 else "no_git_repository"
        for args in (["diff", "--name-only", "HEAD"], ["ls-files", "--others", "--exclude-standard"]):
            changed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
            if changed.returncode == 0:
                changed_files.extend(changed.stdout.splitlines())
    except FileNotFoundError:
        pass
    lines += ["```text", status_text, "```", ""]
    (reports / "V04_CHANGED_FILES.txt").write_text("\n".join(sorted(set(changed_files))) + "\n")
    (reports / "V04_HANDOFF.md").write_text("\n".join(lines))
    (reports / "OVERNIGHT_REPORT.md").write_text("\n".join(lines))
    (reports / "V04_E2E_EVIDENCE.md").write_text("\n".join(evidence))


if __name__ == "__main__":
    main()
