"""First experiment: verified files and a local result page, no UUID lookup."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="standing_contact_probe")
    parser.add_argument("--output", type=Path, help="new output directory (never overwrites an existing one)")
    args = parser.parse_args()
    destination = args.output or ROOT / "outputs" / datetime.now(timezone.utc).strftime("experiment-%Y%m%d-%H%M%S-%f")
    client_python = ROOT / ".client-venv/bin/python"
    if client_python.is_file():
        subprocess.run([str(client_python), str(ROOT / "examples/mcp-client/client.py"), "--docker",
                        "--scenario", args.scenario, "--save-dir", str(destination), "--output", str(destination / "client.json")], check=True)
    else:
        destination = destination.resolve()
        if not destination.is_relative_to(ROOT) or destination == ROOT:
            raise ValueError("offline export directory must be inside this project/bundle")
        if destination.exists():
            raise FileExistsError("choose a new output directory: " + str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        container_output = "/app/exports/" + destination.name
        subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), "-p", "human-models-mcp-night",
                        "run", "--rm", "--no-deps", "-T", "-v", str(destination.parent) + ":/app/exports",
                        "--entrypoint", "python", "runtime", "examples/mcp-client/client.py", "--scenario", args.scenario,
                        "--save-dir", container_output, "--output", container_output + "/client.json"], check=True, cwd=ROOT)
        print("Open result: " + str(destination / "index.html"))


if __name__ == "__main__":
    main()
