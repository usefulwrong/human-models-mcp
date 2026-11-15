"""Build-time environment evidence without host details or secrets."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

root = Path("/app")
source_hash = hashlib.sha256()
for p in sorted((root / "src").rglob("*.py")):
    source_hash.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes())
evidence = {"python": platform.python_version(), "base_image": "python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54",
            "source_sha256": source_hash.hexdigest(),
            "scenario_contracts": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sorted((root / "scenarios").rglob("*.yaml"))},
            "requirements_lock_sha256": hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest(),
            "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
            "system_packages": subprocess.check_output(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True).splitlines()}
(root / "runtime-environment.json").write_text(json.dumps(evidence, indent=2) + "\n")
