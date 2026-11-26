"""Print a relocatable MCP stdio configuration for this checkout."""

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def configuration(mode, form, *, root=ROOT, python=sys.executable):
    if mode == "docker":
        command, name = "docker", "human_models"
        args = ["compose", "-f", str(root / "compose.yaml"), "-p", "human-models-mcp-night",
                "run", "--rm", "--no-deps", "-T"]
        if hasattr(os, "getuid"):
            args += ["--user", f"{os.environ.get('HMM_UID', os.getuid())}:{os.environ.get('HMM_GID', os.getgid())}"]
        args.append("runtime")
    else:
        command = python
        if mode == "anatomy":
            name, args = "anatomy_lab", ["-X", "utf8", str(root / "scripts/native.py"), "anatomy-mcp"]
        else:
            name, args = "human_models", ["-X", "utf8", "-m", "human_models_mcp"]
    values = {"command": command, "args": args, "cwd": str(root)}
    if mode != "docker":
        values["env"] = {"HUMAN_MODELS_HOME": str(root)}
    if form == "json":
        return json.dumps({"mcpServers": {name: values}}, indent=2, ensure_ascii=False) + "\n"
    values |= {"startup_timeout_sec": 30, "tool_timeout_sec": 120}
    lines = [f"[mcp_servers.{name}]"]
    for key, value in values.items():
        if key == "env":
            escaped = json.dumps(value["HUMAN_MODELS_HOME"], ensure_ascii=False)
            lines.append(f"env = {{ HUMAN_MODELS_HOME = {escaped} }}")
        else:
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    body = "\n".join(lines) + "\n"
    assert tomllib.loads(body)["mcp_servers"][name] == values
    return body


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["native", "anatomy", "docker"], default="docker")
    p.add_argument("--format", choices=["toml", "json"], default="toml")
    args = p.parse_args()
    print(configuration(args.mode, args.format), end="")


if __name__ == "__main__":
    main()
