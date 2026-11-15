"""Repeat the documented connector without consuming the production run quota."""

import json
import argparse
import os
from pathlib import Path
import subprocess
import shutil
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    store = ROOT / "reports/e2e-client-runs" / str(uuid4())
    store.mkdir(parents=True)
    env = {**os.environ, "HMM_RESULTS_DIR": str(store)}
    runs = {}
    for scenario, filename in (("elbow_sweep", "fresh-client.json"), ("knee_sweep", "fresh-knee-client.json"),
                               ("activation_pulse", "fresh-forward-client.json"), ("knee_coupled", "fresh-coupled-client.json"),
                               ("loaded_elbow", "fresh-loaded-client.json"), ("wrist_benchmark", "fresh-wrist-client.json"),
                               ("elbow_tracking", "fresh-tracking-client.json"), ("standing_contact_probe", "fresh-contact-client.json"),
                               ("assisted_stance", "fresh-assisted-client.json")):
        if args.demo:
            filename = {"elbow_sweep": "demo.json", "knee_sweep": "knee-demo.json", "activation_pulse": "forward-demo.json",
                        "knee_coupled": "coupled-demo.json", "loaded_elbow": "loaded-demo.json",
                        "wrist_benchmark": "wrist-demo.json", "elbow_tracking": "tracking-demo.json", "standing_contact_probe": "contact-demo.json", "assisted_stance": "assisted-demo.json"}[scenario]
        command = [str(ROOT / ".client-venv/bin/python"), str(ROOT / "examples/mcp-client/client.py"),
                   "--docker", "--scenario", scenario, "--output", str(ROOT / "reports" / filename)]
        if scenario in ("loaded_elbow", "wrist_benchmark", "elbow_tracking", "standing_contact_probe", "assisted_stance"):
            command.extend(["--save-dir", str(ROOT / "reports/e2e-client-runs" / ("downloads-" + store.name) / scenario)])
        subprocess.run(command, env=env, check=True)
        run = json.loads((ROOT / "reports" / filename).read_text())["run"]
        assert (store / run["run_id"] / "manifest.json").is_file()
        runs[scenario] = run["run_id"]
    (ROOT / "reports" / ("demo-store.json" if args.demo else "fresh-clients-store.json")).write_text(json.dumps(
        {"status": "pass", "result_store": str(store.relative_to(ROOT)), "runs": runs}, indent=2) + "\n")
    if args.demo:
        for scenario in ("standing_contact_probe", "assisted_stance"):
            destination = ROOT / "docs/demo_v05" / scenario
            destination.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.json", "series.csv", "summary.json", "animation.gif", "overview.png", "plots.png", "frames.json", "model_recipe.json", "initial_conditions.json", "contact_map.json"):
                shutil.copy2(store / runs[scenario] / name, destination / name)


if __name__ == "__main__":
    main()
