"""No-cache source fixture, separate images and fresh offline physics/render clients; no Git writes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from public_check import public_files
from visual_release_check import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    tag = str(uuid4())
    destination = ROOT / ".cache" / ("clean-v06-" + tag)
    destination.mkdir(parents=True)
    for source in public_files(ROOT):
        if source.is_symlink() or source.is_junction():
            raise ValueError(f"invalid public source path: {source.relative_to(ROOT)}")
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    fingerprint = source_fingerprint(ROOT)
    assert source_fingerprint(destination) == fingerprint
    assert not any((destination / n).exists() for n in ("results", "models", "render_jobs", ".git"))
    env = {**os.environ, "BUILDX_CONFIG": str(ROOT / ".cache/buildx")}

    def run(args, timeout=900):
        subprocess.run(args, cwd=destination, env=env, check=True, timeout=timeout)

    run([sys.executable, "scripts/provision.py"])
    # Reuse only a verified downloaded archive; there is no compiled/build/model/result cache.
    vendor = destination / "render_vendor"
    vendor.mkdir()
    archive = json.loads((ROOT / "renderer.lock.json").read_text())["blender"]["url"].rsplit("/", 1)[-1]
    shutil.copy2(ROOT / "render_vendor" / archive, vendor / archive)
    run([sys.executable, "scripts/provision_renderer.py"])
    science = "human-models-mcp-night-clean-science:" + tag
    renderer = "human-models-mcp-night-clean-renderer:" + tag
    run(["docker", "build", "--no-cache", "-t", science, "."], 1200)
    run(
        [
            "docker",
            "build",
            "--no-cache",
            "-f",
            "Dockerfile.render",
            "--build-arg",
            "SCIENCE_IMAGE=" + science,
            "-t",
            renderer,
            ".",
        ],
        1200,
    )
    compose = destination / "compose.yaml"
    compose.write_text(
        compose.read_text()
        .replace("human-models-mcp-night-runtime:local", science)
        .replace("human-models-mcp-night-renderer:local", renderer)
    )
    for name in ("results", "reports/logs", "render_jobs"):
        (destination / name).mkdir(parents=True, exist_ok=True)
    env.update(HMM_CLIENT_PYTHON=str(ROOT / ".client-venv/bin/python"), HMM_RENDER_IMAGE=renderer)
    project = "hmm-visual-clean-" + tag
    env["COMPOSE_PROJECT_NAME"] = project
    env["HMM_RUNTIME_IMAGE"] = science
    dc = ["docker", "compose", "-f", str(compose), "-p", project]
    run(
        [
            *dc,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "sh",
            "runtime",
            "-c",
            "ruff check --no-cache src tests scripts examples && pytest -q -p no:cacheprovider && python scripts/check_package.py && python scripts/e2e.py",
        ],
        900,
    )
    run([env["HMM_CLIENT_PYTHON"], "scripts/render_e2e.py"], 1200)
    run([*dc, "stop", "renderer"])
    result = {
        "status": "pass",
        "source_sha256": fingerprint,
        "fixture": str(destination.relative_to(ROOT)),
        "git": "operator_managed; no clone or Git mutation",
        "source_state": "exact working-source fixture, not a committed checkout",
        "build_cache": False,
        "initial_results_models_queue": "absent",
        "archive_cache": "SHA-verified official Blender download only",
        "network": "provision/build only; all scientific/render runtime network_mode=none",
        "science_image": subprocess.check_output(
            ["docker", "image", "inspect", science, "--format", "{{.Id}}"], text=True
        ).strip(),
        "renderer_image": subprocess.check_output(
            ["docker", "image", "inspect", renderer, "--format", "{{.Id}}"], text=True
        ).strip(),
        "checks": [
            "fresh models",
            "no-cache two-image build",
            "lint/unit/package",
            "nine real scenarios stdio/HTTP",
            "fresh SDK rendering stdio/HTTP",
            "CPU fallback",
            "independent downloaded scene/media checks",
        ],
        "science_evidence": str((destination / "reports/e2e.json").relative_to(ROOT)),
        "render_evidence": str((destination / "reports/V06_RENDER_CPU.json").relative_to(ROOT)),
    }
    (ROOT / "reports/V06_CLEAN_CHECK.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
