"""Repeat the documented connector without consuming the production run quota."""

import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    store = ROOT / "reports/e2e-client-runs" / str(uuid4())
    store.mkdir(parents=True)
    env = {**os.environ, "HMM_RESULTS_DIR": str(store)}
    runs = {}
    for scenario, filename in (("elbow_sweep", "fresh-client.json"), ("knee_sweep", "fresh-knee-client.json"),
                               ("activation_pulse", "fresh-forward-client.json"), ("knee_coupled", "fresh-coupled-client.json"),
                               ("loaded_elbow", "fresh-loaded-client.json"), ("wrist_benchmark", "fresh-wrist-client.json"),
                               ("elbow_tracking", "fresh-tracking-client.json"), ("standing_contact_probe", "fresh-contact-client.json"),
                               ("assisted_stance", "fresh-assisted-client.json")):
        command = [str(ROOT / ".client-venv/bin/python"), str(ROOT / "examples/mcp-client/client.py"),
                   "--docker", "--scenario", scenario, "--output", str(ROOT / "reports" / filename)]
        if scenario in ("loaded_elbow", "wrist_benchmark", "elbow_tracking", "standing_contact_probe", "assisted_stance"):
            command.extend(["--save-dir", str(ROOT / "reports/e2e-client-runs" / ("downloads-" + store.name) / scenario)])
        subprocess.run(command, env=env, check=True)
        run = json.loads((ROOT / "reports" / filename).read_text())["run"]
        assert (store / run["run_id"] / "manifest.json").is_file()
        runs[scenario] = run["run_id"]
    (ROOT / "reports/fresh-clients-store.json").write_text(json.dumps(
        {"status": "pass", "result_store": str(store.relative_to(ROOT)), "runs": runs}, indent=2) + "\n")


if __name__ == "__main__":
    main()
