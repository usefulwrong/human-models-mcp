"""Rebuild isolated current source with empty stores and no build cache."""

import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from uuid import uuid4

from public_check import check, public_files
from visual_release_check import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    tag = str(uuid4())
    destination = ROOT / ".cache" / ("clean-source-" + tag)
    destination.mkdir(parents=True)
    for source in public_files(ROOT):
        if source.is_symlink():
            raise ValueError(f"symlink in public source: {source.relative_to(ROOT)}")
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    acceptance = check(destination, strict_tree=True)
    if acceptance["status"] != "pass":
        raise ValueError(str(acceptance["failures"]))
    fingerprint = source_fingerprint(destination)
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
    evidence = {"status": "pass",
                "source_sha256": fingerprint, "clone": str(destination.relative_to(ROOT)),
                "image_id": subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip(),
                "build_cache": False, "runtime_network": "none", "initial_results": "absent",
                "source_state": "exact_public_source_fixture",
                "original_git_mutated": False,
                "checks": ["strict_public_source_fixture", "fresh_model_provision", "no_cache_image_build", "unit_package_lint", "stdio_http_real_engine", "fresh_host_motion_client"],
                "e2e_evidence": str((destination / "reports/e2e.json").relative_to(ROOT)),
                "fresh_clients": clients}
    (ROOT / "reports/clean-copy.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
