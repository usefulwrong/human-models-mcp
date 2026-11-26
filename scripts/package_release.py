"""Persist the exact runtime and prove a new offline bundle client works."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("HMM_RUNTIME_IMAGE", "human-models-mcp-night-runtime:local")


def offline_compose(text, image_id, renderer_id):
    compose = yaml.safe_load(text)
    for name, identity in (("runtime", image_id), ("renderer", renderer_id)):
        if identity is None:
            compose['services'].pop(name)
            continue
        service = compose['services'][name]
        service.pop('build', None)
        service.update(image=identity, pull_policy='never')
        service['volumes'] = [v.replace('${HMM_RESULTS_DIR:-./results}', './results') for v in service['volumes']]
    return compose


def read_image_environment(image):
    probe = "import pathlib,json,hashlib; r=pathlib.Path('/app'); d=json.loads((r/'runtime-environment.json').read_text()); d.update({n+'_sha256':hashlib.sha256((r/n).read_bytes()).hexdigest() for n in ('models.lock.json','renderer.lock.json','requirements-render.lock')}); print(json.dumps(d))"
    text = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            "human-models-mcp-night-package-env-" + str(uuid4()),
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "256m",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "python",
            image,
            "-c",
            probe,
        ],
        text=True,
    )
    return json.loads(text)


def image_matches_source(record):
    digest = hashlib.sha256()
    for p in sorted((ROOT / "src").rglob("*.py")):
        digest.update(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes())
    expected = {
        "source_sha256": digest.hexdigest(),
        "scenario_contracts": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "scenarios").rglob("*.yaml"))
        },
        "requirements_lock_sha256": hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
    }
    expected.update(
        {
            n + "_sha256": hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
            for n in ("models.lock.json", "renderer.lock.json", "requirements-render.lock")
        }
    )
    return all(record.get(k) == value for k, value in expected.items())


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    # Package current public demos/source, rather than an older image's source distribution.
    subprocess.run(
        [str(ROOT / ".client-venv/bin/python"), str(ROOT / "scripts/check_package.py")], cwd=ROOT, check=True
    )
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], text=True
    ).strip()
    renderer_tag = os.environ.get("HMM_RENDER_IMAGE", "human-models-mcp-night-renderer:local")
    renderer = subprocess.run(
        ["docker", "image", "inspect", renderer_tag, "--format", "{{.Id}}"], capture_output=True, text=True
    )
    renderer_id = renderer.stdout.strip() if renderer.returncode == 0 else None
    payload = []
    for image in [IMAGE, *([renderer_tag] if renderer_id else [])]:
        payload.append(read_image_environment(image))
    if not image_matches_source(payload[0]):
        raise RuntimeError("Scientific image differs from current source/scenarios/locks; run make build")
    if renderer_id and not image_matches_source(payload[1]):
        renderer_id = None
    destination = ROOT / "release" / ("human-models-mcp-" + str(uuid4()))
    destination.mkdir(parents=True)
    for name in ("results", "reports", "notices", "packages", "render_jobs"):
        (destination / name).mkdir()
    subprocess.run(
        [
            "docker",
            "save",
            "-o",
            str(destination / "image.tar"),
            IMAGE,
            *([renderer_tag] if renderer_id else []),
        ],
        check=True,
    )
    shutil.copy2(ROOT / "scripts/verify_bundle.py", destination / "verify.py")
    for name in ("LICENSE", "CITATION.cff", "models.lock.json", "requirements.lock"):
        shutil.copy2(ROOT / name, destination / name)
    for path in (ROOT / "notices").iterdir():
        if path.is_file():
            shutil.copy2(path, destination / "notices" / path.name)
    packages = list((ROOT / "reports/packages" / version).glob("*"))
    if not any(p.suffix == ".whl" for p in packages) or not any(p.name.endswith(".tar.gz") for p in packages):
        raise RuntimeError("make test must create the wheel and sdist before packaging")
    for path in packages:
        shutil.copy2(path, destination / "packages" / path.name)
    compose = offline_compose((ROOT / "compose.yaml").read_text(), image_id, renderer_id)
    (destination / "compose.yaml").write_text(yaml.safe_dump(compose, sort_keys=False))
    (destination / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/print_client_config.py", destination / "scripts/print_client_config.py")
    shutil.copy2(ROOT / "scripts/experiment.py", destination / "scripts/experiment.py")
    shutil.copy2(ROOT / "scripts/visualize.py", destination / "scripts/visualize.py")
    shutil.copy2(ROOT / "scripts/render_demo.py", destination / "scripts/render_demo.py")
    for name in (
        "renderer.lock.json",
        "requirements-render.lock",
        "visual_sources.json",
        "compose.render-gpu.yaml",
    ):
        shutil.copy2(ROOT / name, destination / name)
    (destination / "README.md").write_text("""# Offline research preview bundle

Contains the exact scientific runtime image, verified model assets, SDK, all
scenario folders, Python source distribution/wheel and license notices.
Docker Engine + Compose and Python 3 for hash verification are required.
No pip install, model download, build or external network is needed.
If bundle.json has a non-null renderer_image_id, it also contains the matching
Blender Cycles runtime. Start a new standalone visual experiment with:

```sh
python3 scripts/render_demo.py --preview
```

That command computes the articulated pushup_flat_palm experiment, prints its
full-cycle acceptance and generates PNG, MP4/GIF, a scene and a passport.
Native paths represent model transmissions and materials are presentation.
GPU rendering is optional. Physics runs on CPU.

From this directory (after copying it entirely to the target project directory):

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
python3 verify.py --load
python3 scripts/experiment.py --scenario standing_contact_probe --output outputs/my-first-contact
python3 scripts/print_client_config.py
```

Choose elbow_sweep, knee_sweep, knee_coupled, activation_pulse, loaded_elbow,
wrist_benchmark, elbow_tracking, standing_contact_probe or assisted_stance.
standing_contact_probe measures native capsule-floor forces; assisted_stance uses an explicit external pelvis support wrench. Neither proves unassisted balance.
loaded_elbow produces saved-state frames, GIF and plots of a soft-fixture initial-value experiment.
The runtime has network_mode=none and uses only this directory's results/reports
mounts. Compose references the immutable image ID and never pulls. For an MCP
host, use command docker with args compose -f /absolute/path/to/compose.yaml -p
human-models-mcp-night run --rm --no-deps -T runtime. Connector
configuration is generated for the current bundle location by python3 scripts/print_client_config.py.

SHA-256 detects changed bytes, not upstream authenticity or clinical validity.
Static poses are geometric coordinate slices. activation_pulse is a short
uncontrolled model initial-value simulation, not exercise or validated human
force prediction. See the full scientific scope packaged inside the image.
No publication, clinical validation or new LLM session is implied by this bundle.
""")
    files = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                files[str(path.relative_to(destination))] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "image_id": image_id,
        "image_tag": IMAGE,
        "renderer_image_id": renderer_id,
        "renderer_image_tag": renderer_tag if renderer_id else None,
        "package_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "runtime_network": "none",
        "clinical_validation": "not_run",
    }
    (destination / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
    relocated = ROOT / "release" / ("human-models-mcp-" + str(uuid4()))
    destination.rename(relocated)
    destination = relocated
    config_text = subprocess.check_output(
        [sys.executable, str(destination / "scripts/print_client_config.py")], cwd="/tmp", text=True
    )
    config = tomllib.loads(config_text)["mcp_servers"]["human_models"]
    assert config["cwd"] == str(destination) and config["args"][2] == str(destination / "compose.yaml")
    subprocess.run([sys.executable, str(destination / "verify.py"), "--load"], cwd=destination, check=True)
    subprocess.run(
        [
            sys.executable,
            str(destination / "scripts/experiment.py"),
            "--scenario",
            "standing_contact_probe",
            "--output",
            str(destination / "outputs/first-contact"),
        ],
        cwd=destination,
        check=True,
        timeout=180,
    )
    assert (destination / "outputs/first-contact/index.html").is_file()
    assert (
        json.loads((destination / "outputs/first-contact/client.json").read_text())["run"]["status"]
        == "computed"
    )
    clients = {}
    for scenario in (
        "elbow_sweep",
        "knee_sweep",
        "activation_pulse",
        "knee_coupled",
        "loaded_elbow",
        "wrist_benchmark",
        "elbow_tracking",
        "standing_contact_probe",
        "assisted_stance",
    ):
        output = destination / "reports" / (scenario + ".json")
        command = [
            str(ROOT / ".client-venv/bin/python"),
            str(ROOT / "examples/mcp-client/client.py"),
            "--compose",
            str(destination / "compose.yaml"),
            "--scenario",
            scenario,
            "--output",
            str(output),
        ]
        if scenario in ("wrist_benchmark", "elbow_tracking", "standing_contact_probe", "assisted_stance"):
            command.extend(["--save-dir", str(destination / "reports" / (scenario + "-files"))])
        subprocess.run(command, check=True)
        clients[scenario] = json.loads(output.read_text())["run"]["run_id"]
    visual = None
    if renderer_id:
        project = "human-models-mcp-night-package-" + uuid4().hex
        dc = ["docker", "compose", "-f", str(destination / "compose.yaml"), "-p", project]
        subprocess.run([*dc, "up", "-d", "--no-deps", "renderer"], cwd=destination, check=True)
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(destination / "scripts/visualize.py"),
                    "render",
                    "--run-id",
                    clients["elbow_tracking"],
                    "--profile",
                    "preview",
                    "--frames",
                    "3",
                    "--device",
                    "cpu",
                    "--wait",
                    "--output",
                    str(destination / "outputs/first-visual"),
                ],
                cwd=destination,
                env={**os.environ, "COMPOSE_PROJECT_NAME": project},
                check=True,
                timeout=180,
            )
            visual = json.loads((destination / "outputs/first-visual/job.json").read_text())
            assert (
                visual["status"] == "completed"
                and (destination / "outputs/first-visual/index.html").is_file()
            )
        finally:
            subprocess.run([*dc, "stop", "renderer"], cwd=destination, check=True)
    evidence = {
        "status": "pass",
        "bundle": str(destination.relative_to(ROOT)),
        "image_id": image_id,
        "image_archive_sha256": files["image.tar"],
        "clients": clients,
        "renderer_image_id": renderer_id,
        "offline_blender_job": visual["job_id"] if visual else None,
        "checks": [
            "archive_hashes",
            "docker_load_identity",
            "new_offline_stdio_clients",
            "real_nine_scenarios",
            "motion_artifact_transfer",
            "named_result_export",
            "relocated_bundle_connector",
            "stdlib_only_first_experiment",
        ],
    }
    (ROOT / "reports/offline-bundle.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
