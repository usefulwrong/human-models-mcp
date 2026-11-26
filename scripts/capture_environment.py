"""Build-time environment evidence without host details or secrets."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import os
import platform
import shutil
import subprocess


def capture(root, destination, *, base_image=None):
    suffix = "-windows-x64" if os.name == "nt" else ""
    lock = root / f"requirements{suffix}.lock"
    source_hash = hashlib.sha256()
    for path in sorted((root / "src").rglob("*.py")):
        source_hash.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    evidence = {
        "python": platform.python_version(),
        "source_sha256": source_hash.hexdigest(),
        "scenario_contracts": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "scenarios").rglob("*.yaml"))
        },
        "requirements_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "system_packages": None,
    }
    if shutil.which("dpkg-query"):
        evidence["system_packages"] = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True
        ).splitlines()
    if base_image is not None:
        evidence["base_image"] = base_image
    for name in ("models.lock.json", "renderer.lock.json", f"requirements-render{suffix}.lock"):
        evidence[name + "_sha256"] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if os.name == "nt":
        path = root / "dependencies-windows-x64.json"
        evidence["dependencies-windows-x64.json_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(destination)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "runtime-environment.json")
    parser.add_argument("--base-image")
    args = parser.parse_args()
    capture(root, args.output, base_image=args.base_image)
