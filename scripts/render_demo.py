"""Create real named render exports; uses the independently exercised public SDK client."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    store = ROOT / "reports/e2e-client-runs" / ("flat-palm-preview-" + str(uuid4()))
    store.mkdir(parents=True)
    destination = ROOT / "outputs" / ("render-preview-" + str(uuid4()))
    env = {**os.environ, "HMM_RESULTS_DIR": str(store)}
    subprocess.run(
        ["docker", "compose", "-p", os.environ.get("COMPOSE_PROJECT_NAME", "human-models-mcp-night"), "up", "-d", "--no-deps", "renderer"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    physical = ROOT / "outputs" / ("render-source-" + str(uuid4()))
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/experiment.py"),
            "--scenario",
            "pushup_flat_palm",
            "--output",
            str(physical),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    run = json.loads((physical / "client.json").read_text())["run"]
    run_id = run["run_id"]
    acceptance = run["scientific"]["acceptance"]["full_pushup"]
    print(f"pushup_flat_palm · full_pushup={acceptance}", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/visualize.py"),
            "render",
            "--run-id",
            run_id,
            "--profile",
            "preview" if args.preview else "scientific",
            "--frames",
            "5" if args.preview else "21",
            "--device",
            "cpu",
            "--wait",
            "--output",
            str(destination),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    print("Render files:", destination)


if __name__ == "__main__":
    main()
