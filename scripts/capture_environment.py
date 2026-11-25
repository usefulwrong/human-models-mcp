"""Build-time environment evidence without host details or secrets."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess


def capture(root, destination, *, base_image=None):
    source_hash = hashlib.sha256()
    for path in sorted((root / "src").rglob("*.py")):
        source_hash.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    evidence = {
        "python": platform.python_version(),
        "source_sha256": source_hash.hexdigest(),
        "scenario_contracts": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "scenarios").rglob("*.yaml"))
        },
        "requirements_lock_sha256": hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest(),
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "system_packages": None,
    }
    if shutil.which("dpkg-query"):
        evidence["system_packages"] = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True
        ).splitlines()
    if base_image is not None:
        evidence["base_image"] = base_image
    for name in ("models.lock.json", "renderer.lock.json", "requirements-render.lock"):
        evidence[name + "_sha256"] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    destination.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "runtime-environment.json")
    parser.add_argument("--base-image")
    args = parser.parse_args()
    capture(root, args.output, base_image=args.base_image)
