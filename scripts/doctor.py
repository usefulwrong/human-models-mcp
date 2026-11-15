"""Read-only host diagnostics. GPU failure never blocks the CPU path."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {"command": args, "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": args, "exit_code": None, "error": str(exc)}


def main():
    commands = [
        ["git", "status", "--short"], ["git", "rev-parse", "HEAD"], ["python3", "--version"],
        ["docker", "version"], ["docker", "compose", "version"], ["free", "-h"],
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        ["nvidia-ctk", "--version"], ["cat", "/proc/driver/nvidia/version"],
        ["docker", "info", "--format", "{{json .Runtimes}}"],
        ["docker", "image", "inspect", "human-models-mcp-night-runtime:local", "--format", "{{.Id}}"],
        ["docker", "run", "--rm", "--name", "human-models-mcp-night-doctor-gpu", "--network", "none",
         "--cpus", "1", "--memory", "256m", "--pids-limit", "64", "--cap-drop", "ALL",
         "--security-opt", "no-new-privileges", "--gpus", "all",
         "python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54",
         "nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
    ]
    results = [command(args) for args in commands]
    lock = json.loads((ROOT / "models.lock.json").read_text())
    bad = [x["path"] for x in lock["files"] if not (ROOT / "models" / x["path"]).is_file()
           or hashlib.sha256((ROOT / "models" / x["path"]).read_bytes()).hexdigest() != x["sha256"]]
    dns = {}
    for host in ("pypi.org", "raw.githubusercontent.com"):
        try:
            dns[host] = socket.gethostbyname(host)
        except OSError as exc:
            dns[host] = str(exc)
    disk = shutil.disk_usage(ROOT)
    doctor = {"timestamp": datetime.now(timezone.utc).isoformat(), "commands": results,
              "dns": dns, "disk_free_bytes": disk.free,
              "cpu": next((s.split(":", 1)[1].strip() for s in Path("/proc/cpuinfo").read_text().splitlines() if s.startswith("model name")), "unknown"),
              "model_integrity": {"status": "pass" if not bad else "fail", "bad_files": bad},
              "gpu_note": "Host NVML may fail in this sandbox; make gpu-smoke checks the container runtime separately.",
              "cdi_files": [str(p) for base in ("/etc/cdi", "/var/run/cdi") for p in Path(base).glob("*.yaml")]}
    (ROOT / "reports/logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports/doctor.json").write_text(json.dumps(doctor, indent=2) + "\n")
    required = results[3]["exit_code"] == 0 and results[4]["exit_code"] == 0 and not bad and disk.free > 128 * 1024**2
    print(json.dumps({"status": "pass" if required else "fail", "cpu": doctor["cpu"],
                      "model_integrity": doctor["model_integrity"], "disk_free_gib": round(disk.free / 1024**3, 1),
                      "details": "reports/doctor.json"}))
    raise SystemExit(0 if required else 1)


if __name__ == "__main__":
    main()
