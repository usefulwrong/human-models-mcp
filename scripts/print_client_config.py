"""Print portable-to-this-checkout Codex configuration; never edit user config."""

import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
args = ["compose", "-f", str(root / "compose.yaml"), "-p", "human-models-mcp-night",
        "run", "--rm", "--no-deps", "-T", "--user",
        os.environ.get("HMM_UID", str(os.getuid())) + ":" + os.environ.get("HMM_GID", str(os.getgid())), "runtime"]
print('[mcp_servers.human_models]\ncommand = "docker"')
print("args = " + json.dumps(args))
print("cwd = " + json.dumps(str(root)))
print("startup_timeout_sec = 30\ntool_timeout_sec = 120")
