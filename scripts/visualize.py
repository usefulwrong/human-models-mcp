"""Stdlib host launcher for the standalone toolkit; Docker starts only on the host."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
args = sys.argv[1:]
command = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "compose.yaml"),
    "-p",
    os.environ.get("COMPOSE_PROJECT_NAME", "human-models-mcp-night"),
    "run",
    "--rm",
    "--no-deps",
    "-T",
]
if "--output" in args:
    i = args.index("--output") + 1
    destination = Path(args[i]).resolve()
    if not destination.is_relative_to(ROOT) or destination == ROOT:
        raise ValueError("export must be within project directory")
    if destination.exists():
        raise FileExistsError("choose a new export directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command += ["-v", str(destination.parent) + ":/app/exports"]
    args[i] = "/app/exports/" + destination.name
subprocess.run(
    [*command, "--entrypoint", "python", "runtime", "-m", "human_models_mcp.visualize", *args],
    cwd=ROOT,
    check=True,
)
if "--output" in sys.argv:
    print("Open render: " + str(destination / "index.html"))
