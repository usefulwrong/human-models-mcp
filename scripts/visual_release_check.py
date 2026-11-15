"""Execute v0.6 visualization gates; preserve historical v0.5/Git release policy."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md",
    "pyproject.toml",
    "requirements.in",
    "requirements.lock",
    "models.lock.json",
    "Dockerfile",
    "compose.yaml",
    "Makefile",
    "MANIFEST.in",
    ".dockerignore",
    "LICENSE",
    "CITATION.cff",
    "Dockerfile.render",
    "Dockerfile.render.dockerignore",
    "compose.render-gpu.yaml",
    "renderer.lock.json",
    "requirements-render.lock",
    "visual_sources.json",
)


def source_fingerprint(root):
    files = [root / name for name in ROOT_FILES]
    for name in ("src", "scenarios", "scripts", "tests", "skills", "examples", "notices", "benchmarks"):
        files += [
            p
            for p in (root / name).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and ".egg-info" not in str(p)
        ]
    files += [
        p
        for p in (root / "docs").rglob("*.md")
        if not any(part.startswith("demo") for part in p.relative_to(root / "docs").parts)
    ]
    digest = hashlib.sha256()
    for p in sorted(files):
        digest.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="reuse this check's actual command results only if source is unchanged; add current independent agent/audit evidence",
    )
    args = parser.parse_args()
    report = ROOT / "reports/V06_RELEASE_CHECK.json"
    fingerprint = source_fingerprint(ROOT)
    if args.finalize:
        result = json.loads(report.read_text())
        if result["source_sha256"] != fingerprint:
            raise RuntimeError("source changed; rerun make visual-release-check")
    else:
        result = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": fingerprint,
            "gates": {},
        }
        for target, timeout in (
            ("doctor", 180),
            ("render-build", 1800),
            ("test", 600),
            ("e2e", 900),
            ("visual-regression", 60),
            ("gpu-smoke", 600),
            ("render-e2e", 1200),
            ("render-gpu-smoke", 1800),
            ("render-demo", 60),
            ("render-faults", 900),
            ("visual-clean-check", 3600),
            ("package", 1800),
            ("render-preview", 600),
        ):
            log = ROOT / "reports/logs" / ("v06-final-" + target + ".log")
            log.parent.mkdir(parents=True, exist_ok=True)
            print("Running make", target, "->", log.relative_to(ROOT), flush=True)
            start = time.monotonic()
            with log.open("w") as stream:
                try:
                    code = subprocess.run(
                        ["make", target], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout
                    ).returncode
                except subprocess.TimeoutExpired:
                    code = 124
            result["gates"][target] = {
                "status": "pass" if code == 0 else "fail",
                "required": True,
                "command": "make " + target,
                "exit_code": code,
                "seconds": round(time.monotonic() - start, 3),
                "log": str(log.relative_to(ROOT)),
            }
            report.write_text(json.dumps(result, indent=2) + "\n")
            print(target, code, flush=True)
    result["gates"]["source_unchanged"] = {
        "status": "pass" if source_fingerprint(ROOT) == fingerprint else "fail",
        "required": True,
    }
    for name, filename in (
        ("independent_llm", "V06_AGENT_EVIDENCE.json"),
        ("critical_visual_audit", "V06_FINAL_AUDIT.json"),
    ):
        path = ROOT / "reports" / filename
        evidence = json.loads(path.read_text()) if path.exists() else {}
        ok = evidence.get("status") == "pass" and evidence.get("source_sha256") == fingerprint
        result["gates"][name] = {
            "status": "pass" if ok else "not_run",
            "required": name == "critical_visual_audit",
            "evidence": str(path.relative_to(ROOT)),
        }
    passed = all(g["status"] == "pass" for g in result["gates"].values() if g["required"])
    result.update(
        status="VISUAL_PIPELINE_READY" if passed else "PARTIAL",
        package_version="0.6.0",
        anatomical_layer_status="registration_unverified; no external anatomical layer integrated",
        anatomical_layer_verified=False,
        clinical_validation="not_run",
        human_accuracy_validation="not_promoted_by_visualization",
        timestamp=datetime.now(timezone.utc).isoformat(),
        git_policy="OPERATOR_MANAGED; no Git writes or public-release claim",
    )
    result["head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result["git_status"] = subprocess.check_output(
        ["git", "status", "--short"], cwd=ROOT, text=True
    ).splitlines()
    result["images"] = {
        name: subprocess.check_output(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"], text=True
        ).strip()
        for name, tag in (
            ("science", "human-models-mcp-night-runtime:local"),
            ("renderer", "human-models-mcp-night-renderer:local"),
        )
    }
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
