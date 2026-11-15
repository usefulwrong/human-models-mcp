"""Rebuild isolated current source with empty stores and no build cache."""

import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from uuid import uuid4

from release_check import source_fingerprint, git_read

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ["src", "scenarios", "scripts", "tests", "skills", "examples", "notices", "benchmarks", "pyproject.toml", "requirements.in",
           "requirements.lock", "models.lock.json", "Dockerfile", "compose.yaml", "Makefile", "MANIFEST.in", ".dockerignore", "LICENSE", "CITATION.cff"]


def main():
    head = git_read("rev-parse", "HEAD")
    versioned = head.returncode == 0
    changed = []
    if versioned:
        for command in (["git", "diff", "HEAD", "--name-only", "-z"], ["git", "ls-files", "--others", "--exclude-standard", "-z"]):
            changed.extend(subprocess.check_output(command, cwd=ROOT).decode().split("\0"))
    dirty = any(p and not p.startswith(("reports/", "docs/demo")) for p in changed)
    tag = str(uuid4())
    destination = ROOT / ".cache" / ("clean-v05-" + tag)
    if versioned:
        subprocess.run(["git", "clone", "--no-hardlinks", str(ROOT), str(destination)], check=True)
    else:
        destination.mkdir(parents=True)
    assert not (destination / "results").exists()
    if dirty or not versioned:
        # An isolated test fixture, not a substitute source archive or invented Git history.
        for name in ("src", "scenarios", "scripts", "tests", "skills", "examples", "notices", "docs", "benchmarks"):
            shutil.copytree(ROOT / name, destination / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        for name in ("pyproject.toml", "requirements.in", "requirements.lock", "models.lock.json", "Dockerfile", "compose.yaml",
                     "Makefile", "MANIFEST.in", ".dockerignore", "LICENSE", "CITATION.cff", "README.md"):
            shutil.copy2(ROOT / name, destination / name)
    assert source_fingerprint(destination) == source_fingerprint(ROOT)
    subprocess.run([sys.executable, "scripts/provision.py"], cwd=destination, check=True, timeout=300)
    for name in ("results", "reports/logs"):
        (destination / name).mkdir(parents=True, exist_ok=True)
    image = "human-models-mcp-night-clean:" + tag
    env = {**os.environ, "BUILDX_CONFIG": str(ROOT / ".cache/buildx")}
    subprocess.run(["docker", "build", "--no-cache", "-t", image, "."], cwd=destination, env=env, check=True, timeout=900)
    sandbox = ["docker", "run", "--rm", "--name", "human-models-mcp-night-clean-" + tag,
               "--network", "none", "--cpus", "2", "--memory", "3g", "--pids-limit", "128",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--tmpfs", "/tmp:size=512m,mode=1777", "-v", f"{destination / 'results'}:/app/results",
               "-v", f"{destination / 'reports'}:/app/reports", "--entrypoint", "sh", image, "-c"]
    subprocess.run([*sandbox, "ruff check --no-cache src tests scripts examples && pytest -q -p no:cacheprovider && python scripts/check_package.py && python scripts/e2e.py"],
                   cwd=destination, check=True, timeout=600)
    compose = destination / "compose.yaml"
    compose.write_text(compose.read_text().replace("human-models-mcp-night-runtime:local", image))
    clients = {}
    for scenario in ("loaded_elbow", "wrist_benchmark", "elbow_tracking", "standing_contact_probe", "assisted_stance"):
        client_output = destination / "reports" / ("clean-" + scenario + ".json")
        subprocess.run([str(ROOT / ".client-venv/bin/python"), str(destination / "examples/mcp-client/client.py"),
                        "--compose", str(compose), "--scenario", scenario, "--output", str(client_output),
                        "--save-dir", str(destination / "reports" / (scenario + "-files"))], check=True, timeout=180)
        clients[scenario] = str(client_output.relative_to(ROOT))
    e2e = json.loads((destination / "reports/e2e.json").read_text())
    assert e2e["status"] == "pass" and e2e["stdio"]["v03"]["loaded_elbow"]["run"]["status"] == "computed"
    evidence = {"status": "pass", "head": head.stdout.strip() if versioned else "no_git_repository",
                "source_sha256": source_fingerprint(ROOT), "clone": str(destination.relative_to(ROOT)),
                "image_id": subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip(),
                "build_cache": False, "runtime_network": "none", "initial_results": "absent",
                "source_state": "unversioned_fixture" if not versioned else "working_tree_overlay" if dirty else "committed",
                "original_git_mutated": False,
                "checks": ["fresh_git_clone" if versioned else "unversioned_source_fixture", "fresh_model_provision", "no_cache_image_build", "unit_package_lint", "stdio_http_real_engine", "fresh_host_motion_client"],
                "e2e_evidence": str((destination / "reports/e2e.json").relative_to(ROOT)),
                "fresh_clients": clients}
    (ROOT / "reports/clean-copy.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
