"""Render current v0.3 handover from the actual release gates and protocol evidence."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    reports = ROOT / "reports"
    release = json.loads((reports / "RELEASE_CHECK.json").read_text())

    def observed(name, gate):
        path = reports / name
        return json.loads(path.read_text()) if release["gates"].get(gate, {}).get("status") == "pass" and path.is_file() else {}

    e2e = observed("e2e.json", "e2e")
    bundle = observed("offline-bundle.json", "package")
    clean = observed("clean-copy.json", "clean-check")
    gpu = observed("gpu.json", "gpu-smoke")
    doctor = observed("doctor.json", "doctor")
    lines = ["# UsefulWrong / human-models-mcp 0.3.0 — iteration handover", "",
             f"**RELEASE_STATUS: {release['release_status']}**", "",
             f"Checked at {release['timestamp']}. Existing Git HEAD: `{release['head']}`. Tested working-tree source is identified by the fingerprint; no new commit could be written.",
             f"Runtime image: `{release['image_id']}`.", f"Runtime source fingerprint: `{release['source_sha256']}`.", "",
             "## Independent baseline acceptance", "",
             "The clean initial source was 0.2.0 at `52da8e0bfea176963c117000ca7dd7fabf78031e`. Before edits, make doctor/build/test/e2e all exited 0; 35 tests passed, and all three old experiments ran through real stdio/HTTP and fresh SDK clients. See [V03_BASELINE.json](V03_BASELINE.json) and logs/v03-baseline-*.log. Old reports alone were not accepted as evidence.", "",
             "## Actual commands", "", "| Command | Exit | Status | Seconds | Log |", "| --- | --- | --- | --- | --- |"]
    for gate in release["gates"].values():
        if "command" in gate:
            lines.append(f"| `{gate['command']}` | {gate['exit_code']} | {gate['status']} | {gate['seconds']} | `{gate['log']}` |")
    lines += ["", "Outer command: `make release-check`; exit is 0 only for RESEARCH_PREVIEW_READY. [Machine gates](RELEASE_CHECK_V03.json).", "",
              "## Implemented changes", "",
              "- Original elbow_sweep, knee_sweep and activation_pulse retained with their original numerical interpretation.",
              "- knee_coupled follows eight source tibial/patellar equality polynomials, checks full-interval dependent limits, engine residuals, implicit constraint tangent and path finite differences. It is prescribed static geometry, not integrated movement.",
              "- loaded_elbow performs full-model forward dynamics with a documented soft pelvis fixture, one muscle excitation and a constant generalized elbow torque. It saves numerical trajectories and full integration states.",
              "- 21 raw headless PNG frames, state-aligned graphs, overview and slowed GIF restore those saved states with a fixed camera. State/time/model/CSV/frame hashes connect the artifacts.",
              "- Correct native free/ball/slide/hinge metadata; required rendering failure now fails the overall run; stale running records recover to interrupted failures under the executor lock; parent-death signaling prevents orphan workers.",
              "- FTS5 also indexes all primary joint identifiers with pinned source/hash/license. Three skills describe actual API semantics and new cases.",
              "", "## Measured observations and E2E", ""]
    evidence_lines = ["# Real MCP E2E evidence — v0.3.0", "", "Original commands: `make e2e`, `make gpu-smoke`, `make package`, `make clean-check`; final invocation through `make release-check`.", "",
                      "Official MCP SDK 2.3.0 initializes/discovers/calls tools over stdio and container-loopback Streamable HTTP. Runtime containers use network_mode=none; no external scientific runtime network is available.", ""]
    if e2e:
        lines += ["All five scenarios ran on both transports; independent host SDK processes ran each through the documented Docker connector. The scenario-authoring workflow creates a temporary valid folder, discovers and executes it; malformed manifests/rules are quarantined. These are new deterministic SDK processes, not a separate LLM session.", "",
                  "Discovered tools: " + ", ".join(f"`{x}`" for x in e2e["stdio"]["tools"]) + ".", "",
                  "All observations below are numerical_sanity only, without experimental human comparison or clinical validation.", "",
                  "| Scenario | Metric | Value | Unit |", "| --- | --- | --- | --- |"]
        for transport in ("stdio", "http"):
            evidence_lines += [f"## {transport}", "", f"Negotiated protocol: `{e2e[transport]['protocol']}`.", ""]
            source = e2e[transport]
            runs = [("elbow_sweep", source["run"]), ("knee_sweep", source["knee"]["run"]),
                    ("activation_pulse", source["forward"]["run"]), ("knee_coupled", source["v03"]["coupled_knee"]["run"]),
                    ("loaded_elbow", source["v03"]["loaded_elbow"]["run"])]
            for name, run in runs:
                evidence_lines += [f"Real run_scenario output for `{name}` (UUID `{run['run_id']}`):", "", "```json", json.dumps(run, indent=2), "```", ""]
                if transport == "stdio":
                    for metric in run["outputs"]["metrics"]:
                        lines.append(f"| {name} | {metric['name']} | {metric['value']:.12g} | {metric['unit']} |")
            observation = {name: {k: v for k, v in item.items() if k not in ("run", "csv")} for name, item in source["v03"].items()}
            evidence_lines += ["Independent numerical observations and checks:", "", "```json", json.dumps(observation, indent=2), "```", ""]
        lines += ["", f"Raw protocol evidence: [e2e.json](e2e.json). Persistent store: `{e2e['result_store']}`.",
                  "Source model: [pinned MS-Human-700](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700), Apache-2.0. Citation: Zuo, He, Shao and Sui, Self model for embodied intelligence, ICRA 2024, pp. 13062–13069, as declared by the upstream card."]
    else:
        lines.append("Current real scientific E2E failed or did not run. No old result is promoted to a current PASS.")
    lines += ["", "## Hardware, artifacts and reproduction", "", f"CPU: {doctor.get('cpu', 'not_run')}. Physics backend: CPU."]
    for command in doctor.get("commands", []):
        if command.get("exit_code") == 0 and "nvidia-smi" in command.get("command", []):
            lines.append("Observed GPU query: `" + command["stdout"].strip() + "`.")
    if gpu:
        lines.append(f"21 motion frames rendered on `{gpu['run']['render']['gl_renderer']}`, render_backend=nvidia_egl; physics_backend=cpu. Software OSMesa rendering separately passed in the CPU E2E.")
    for name, gate in (("demo-store.json", "demo"), ("fresh-clients-store.json", "e2e"), ("gpu.json", "gpu-smoke")):
        data = observed(name, gate)
        if data:
            lines.append(f"- `{name}` locates persistent results: `{data.get('result_store', 'see evidence')}`.")
    lines += ["", "Scientific display subset: [animation](../docs/demo_v03/animation.gif), [overview](../docs/demo_v03/overview.png), [plots](../docs/demo_v03/plots.png), [CSV](../docs/demo_v03/series.csv), [manifest](../docs/demo_v03/manifest.json). Full raw PNGs/states remain in the demo store. All are engine-derived, without generated anatomy.", "",
              "```sh", "make build", "make doctor", "make test", "make e2e", "make demo", "make release-check", "```", "",
              "Agent connector: `python3 scripts/print_client_config.py`; an independent client is `.client-venv/bin/python examples/mcp-client/client.py --docker --scenario loaded_elbow --output reports/my-motion.json`. Retrieve UUID artifacts through get_artifact, not container-local paths."]
    if bundle:
        lines += ["", f"Verified offline bundle: `{bundle['bundle']}`; image `{bundle['image_id']}`; archive SHA-256 `{bundle['image_archive_sha256']}`. All five fresh offline clients passed after hash verification and Docker load. Use its README and `python3 verify.py --load`; no runtime pip/download/build is required."]
    if clean:
        lines += ["", f"Isolated Git-clone test fixture: `{clean['clone']}`; source state `{clean['source_state']}`; no-cache image `{clean['image_id']}`; [clean-copy evidence](clean-copy.json). Current working source overlaid and fingerprint-checked, empty results, newly provisioned model, unit/package/lint, both real transports and a fresh host motion client passed. This is not a clean committed checkout claim."]
    lines += ["", "## Scientific limits, failures encountered and remaining risks", "",
              "- No experimental human dataset or clinical validation. Numerical agreement, same-engine restart and finite differences do not validate muscle parameters or human movement safety. Organs, breathing, pathology, age/sex customization, injury risk and exercise clearance are unsupported.",
              "- Fixed knee slices are not constrained physiology. Coupled mode enforces only eight local source equalities; it does not certify all constraints, collisions or equilibrium. The source rotation2 polynomial exceeds its own bound near 0.803 rad; 0.2–1.0 coupled requests are rejected instead of clipped.",
              "- The loaded experiment has an artificial compliant support and prescribed generalized torque, no floor/controller/equilibrium calibration. All other DOFs evolve. Signed actuator force is model transmission force; the work check is quadrature accounting, not full-system energy conservation.",
              "- Initial fixture probe used the MuJoCo default offset anchor and moved the pelvis about 0.147 m. The implemented recipe explicitly anchors the initial pelvis origin; measured default displacement is about 0.000504 m. Preliminary probe results are not the final demo.",
              "- The first SIGKILL test mistook a platform-query subprocess for the scientific worker and failed before a manifest existed. It now matches the actual worker command line. The corrected real worker/executor death tests pass in the accepted suite.",
              "- Direct docker compose build was denied writing ~/.docker/buildx/activity (read-only filesystem); permitted retry used project BUILDX_CONFIG=.cache/buildx and succeeded. No escalation or host settings change was used.",
              "- Authorized command `git add .gitignore CITATION.cff Dockerfile MANIFEST.in Makefile README.md pyproject.toml requirements.in requirements.lock src scenarios scripts tests skills docs examples notices reports/SCIENTIFIC_AUDIT.md reports/V03_BASELINE.json` exited 128: `.git/index.lock: Read-only file system`. No commit or Git mutation succeeded. The isolated build fixture overlays current working files on a clone and checks their exact source fingerprint; it is not new source history or a substitute versioning archive.",
              "- MjSpec diagnostic XML can round values; exact source plus the recorded fixture recipe/timestep reconstruct the model. Debian apt is not snapshot-pinned; preserve the tested offline image for its exact OS libraries. SHA-256 establishes consistency, not hostile-distributor authenticity.",
              "- HTTP remains container-loopback only. No new LLM session, second engine execution, normative limits or whole-person validation is claimed. Atlas and physiology options are research comparisons only.", "",
              "## Follow-up (at most five)", "",
              "1. Resolve the upstream knee polynomial/range conflict with the model authors before expanding the coupled interval.",
              "2. Select an openly licensed independent experimental dataset and define a muscle/kinematics comparison task.",
              "3. Calibrate any longer task/controller/support and perform step/solver sensitivity studies before describing functional movement.",
              "4. Review collision coverage and licensed surface/volume assets before implementing the proposed pose-comparison layers.",
              "5. Before public hosting, design multi-user authentication/isolation; current transport remains local.", "",
              "## Changes and Git", "",
              "Local commits were explicitly authorized, but the managed filesystem prevents writes to the original .git. No commit, push or publication occurred. [CHANGED_FILES.txt](CHANGED_FILES.txt) lists changed source/docs/report files; the Git diff remains reviewable. Existing HEAD is unchanged; tested working source is identified by the source fingerprint and exact offline image.", "",
              "Recorded git status --short at release-check completion (generated evidence may be modified):", "", "```text",
              (reports / "logs/git-status.txt").read_text().rstrip() if (reports / "logs/git-status.txt").is_file() else "not_run", "```", ""]
    body = "\n".join(lines)
    (reports / "ITERATION_V03.md").write_text(body)
    (reports / "OVERNIGHT_REPORT.md").write_text(body)
    evidence_lines += ["## Interpretation boundary", "", "All checks establish numerical consistency and the implemented software contract. Experimental human comparison and clinical validation are not_run. A fresh SDK process is not a newly launched LLM session. See SCIENTIFIC_AUDIT.md and RELEASE_CHECK_V03.json."]
    (reports / "E2E_EVIDENCE_V03.md").write_text("\n".join(evidence_lines) + "\n")
    changed = []
    if (ROOT / ".git").exists():
        diff = subprocess.run(["git", "diff", "--name-only", "52da8e0bfea176963c117000ca7dd7fabf78031e"], cwd=ROOT, text=True, capture_output=True)
        if diff.returncode == 0:
            changed.extend(diff.stdout.splitlines())
        changed.extend(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    (reports / "CHANGED_FILES.txt").write_text("\n".join(sorted(set(changed))) + "\n")


if __name__ == "__main__":
    main()
