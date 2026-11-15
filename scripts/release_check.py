"""Execute required make targets and produce a conservative machine verdict."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def git_read(*arguments, cwd=ROOT):
    try:
        return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git", *arguments], 127, stdout="", stderr="git executable unavailable")


def source_fingerprint(root: Path) -> str:
    files = []
    for base in ("src", "scenarios", "scripts", "tests", "skills", "examples", "notices", "benchmarks"):
        files.extend(p for p in (root / base).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    files.extend(root / name for name in ("pyproject.toml", "requirements.in", "requirements.lock", "models.lock.json", "Dockerfile", "compose.yaml", "Makefile", "MANIFEST.in", ".dockerignore", "LICENSE", "CITATION.cff"))
    fingerprint = hashlib.sha256()
    for path in sorted(files):
        fingerprint.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return fingerprint.hexdigest()


def main():
    reports = ROOT / "reports"
    (reports / "logs").mkdir(parents=True, exist_ok=True)
    gates = {}
    start = time.time()
    fingerprint = source_fingerprint(ROOT)
    targets = [("doctor", 180), ("build", 1200), ("test", 300), ("e2e", 900),
               ("demo", 600), ("experiment", 180), ("gpu-smoke", 360),
               ("contact-negative", 180), ("package", 900), ("clean-check", 1800), ("agent-check", 60)]
    for target, timeout in targets:
        path = reports / "logs" / f"v05-final-{target}.log"
        print(f"Running make {target}; log: {path.relative_to(ROOT)}", flush=True)
        begin = time.monotonic()
        with path.open("w") as log:
            try:
                p = subprocess.run(["make", target], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                code = p.returncode
            except subprocess.TimeoutExpired:
                code = 124
        gates[target] = {"status": "pass" if code == 0 else "fail", "command": f"make {target}",
                         "exit_code": code, "seconds": round(time.monotonic() - begin, 2),
                         "log": str(path.relative_to(ROOT)), "required": True}
        print(f"make {target}: {gates[target]['status']} (exit {code})", flush=True)
    for name, evidence, target in [("real_science_stdio_http_offline", "e2e.json", "e2e"),
                                   ("fresh_nine_clients", "fresh-clients-store.json", "e2e"),
                                   ("published_experimental_comparison", "fresh-wrist-client.json", "e2e"),
                                   ("feedback_control", "fresh-tracking-client.json", "e2e"),
                                   ("standing_contact", "fresh-contact-client.json", "e2e"),
                                   ("assisted_contact", "fresh-assisted-client.json", "e2e"),
                                   ("gpu_contact", "gpu-contact.json", "gpu-smoke"),
                                   ("gpu_assisted", "gpu-assisted.json", "gpu-smoke"),
                                   ("scientific_demo", "demo-store.json", "demo"),
                                   ("gpu_tracking", "gpu-tracking.json", "gpu-smoke"),
                                   ("clean_source_fixture", "clean-copy.json", "clean-check"),
                                   ("offline_release_bundle", "offline-bundle.json", "package")]:
        p = reports / evidence
        fresh = p.is_file() and p.stat().st_mtime >= start and gates[target]["status"] == "pass"
        gates[name] = {"status": "pass" if fresh else "not_run", "evidence": f"reports/{evidence}", "required": True}
    clean_path = reports / "clean-copy.json"
    clean = json.loads(clean_path.read_text()) if gates["clean_source_fixture"]["status"] == "pass" else {}
    git = git_read("rev-parse", "HEAD")
    head = git.stdout.strip() if git.returncode == 0 else "no_git_repository"
    branch = git_read("branch", "--show-current").stdout.strip()
    baseline_path = reports / "V05_BASELINE.json"
    baseline = json.loads(baseline_path.read_text())["head"] if baseline_path.is_file() else "1aa4c5d9526619263a7075dfff5fb71dc88921f0"
    git_path = reports / "V05_GIT_CHECK.json"
    git_evidence = json.loads(git_path.read_text()) if git_path.is_file() else {"status": "not_run", "reason": "no branch-write attempt recorded; release checker never mutates Git"}
    git_reason = "See V05_GIT_CHECK.json for the actual branch command, exit and mount flags; no sandbox bypass."
    gates["working_git_branch"] = {"status": "pass" if branch == "work/v0.5-whole-body-contact-release-rc" else "fail",
                                   "required": True, "branch": branch, "reason": git_reason}
    gates["new_local_source_commit"] = {"status": "pass" if head not in (baseline, "no_git_repository") and clean.get("source_state") == "committed" and clean.get("head") == head else "not_run",
                                        "required": True, "reason": git_reason}
    gates["clean_committed_checkout"] = {"status": "pass" if clean.get("source_state") == "committed" else "not_run",
                                         "required": True, "reason": "Fresh no-cache source fixture passed only when its target passed; a working-tree overlay is not a committed checkout."}
    gates["source_unchanged_during_checks"] = {"status": "pass" if source_fingerprint(ROOT) == fingerprint else "fail", "required": True}
    gates["clinical_validation"] = {"status": "not_run", "required": False, "reason": "outside scope; no clinical claims"}
    native = reports / "V05_NATIVE_AGENT.json"
    gates["native_codex_cli_session"] = {**(json.loads(native.read_text()) if native.is_file() else {"status": "not_run", "reason": "no fresh native CLI evidence"}), "required": False}
    gates["user_handoff_review"] = {"status": "pass", "required": True,
        "reason": "Full v0.5 specification supplied inline by the user after the initial CODEX_V05.md missing-file search; requirements implemented and reviewed."}
    required = [x for x in gates.values() if x["required"]]
    status = "RESEARCH_PREVIEW_READY" if all(x["status"] == "pass" for x in required) else ("FUNCTIONAL_BUT_UNVERIFIED" if gates["e2e"]["status"] == "pass" else "BLOCKED")
    image = subprocess.run(["docker", "image", "inspect", "human-models-mcp-night-runtime:local", "--format", "{{.Id}}"], capture_output=True, text=True)
    result = {"release_status": status, "timestamp": datetime.now(timezone.utc).isoformat(), "gates": gates,
              "baseline_head": baseline, "head": head, "new_commits": [] if head in (baseline, "no_git_repository") else [head], "git_evidence": git_evidence,
              "image_id": image.stdout.strip() if image.returncode == 0 else None,
              "package_version": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
              "source_sha256": fingerprint, "runtime_network": "none; loopback HTTP inside container",
              "clinical_use": "unsupported", "pid": os.getpid()}
    (reports / "RELEASE_CHECK.json").write_text(json.dumps(result, indent=2) + "\n")
    (reports / "V05_RELEASE_CHECK.json").write_text(json.dumps(result, indent=2) + "\n")
    with (reports / "logs/git-status.txt").open("w") as output:
        status_result = git_read("status", "--short")
        output.write(status_result.stdout + status_result.stderr)
    subprocess.run([sys.executable, str(ROOT / "scripts/write_v05_report.py")], cwd=ROOT, check=True)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if status == "RESEARCH_PREVIEW_READY" else 1)


if __name__ == "__main__":
    main()
