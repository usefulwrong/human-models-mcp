"""Invoke the existing atlas builder with the pinned portable Node runtime."""

import json
import os
from pathlib import Path
import subprocess
import sys


def install(root, runtime, cache, environment, offline, prepare=False):
    site = Path(environment["HMM_LAB_SITE"])
    destination = site.parent
    lock = root / "scripts/anatomy_lab/sources.lock.json"
    terms = json.loads(lock.read_text(encoding="utf-8"))
    print("BodyParts3D data are provisioned for local use. Review the pinned source terms:", flush=True)
    for link in dict.fromkeys(item["terms_url"] for item in terms.values()):
        print(link, flush=True)
    if not prepare and (destination / "source-receipt.json").is_file():
        print(f"Anatomy Explorer already exists at {destination}.", flush=True)
        return
    cmd = [sys.executable, "-X", "utf8", str(lock.with_name("provision.py")),
           str(destination), "--cache", str(cache / "anatomy-sources")]
    if offline:
        cmd.append("--offline")
    if prepare:
        cmd.append("--cache-only")
    subprocess.run(cmd, cwd=root, env={**os.environ,
                   "HMM_NODE_BIN": str(runtime / "vendor/node/node.exe")}, check=True)
