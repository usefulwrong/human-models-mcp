"""Optional bounded NVIDIA EGL run, without modifying host drivers."""

import json
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def exercise(scenario: str, filename: str):
    store = ROOT / "reports/e2e-client-runs" / str(uuid4())
    store.mkdir(parents=True)
    args = ["docker", "run", "--rm", "--name", "human-models-mcp-night-egl", "--network", "none",
            "--cpus", "2", "--memory", "3g", "--pids-limit", "128", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:size=512m,mode=1777",
            "--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute", "-e", "MUJOCO_GL=egl",
            "--mount", f"type=bind,src={store},dst=/app/results",
            "--mount", f"type=bind,src={ROOT / 'reports'},dst=/app/reports", "--entrypoint", "python",
            "human-models-mcp-night-runtime:local", "examples/mcp-client/client.py", "--scenario", scenario, "--output", "reports/" + filename]
    p = subprocess.run(args, cwd=ROOT, timeout=180)
    if p.returncode:
        raise SystemExit(p.returncode)
    data = json.loads((ROOT / "reports" / filename).read_text())
    assert data["run"]["execution"]["physics_backend"] == "cpu"
    assert data["run"]["execution"]["render_backend"] == "nvidia_egl", data["run"].get("render")
    assert "NVIDIA" in data["run"]["render"]["gl_vendor"]
    assert data["motion"]["frames"] == 21
    cpu_evidence = ROOT / "reports/e2e.json"
    if cpu_evidence.is_file():
        evidence = json.loads(cpu_evidence.read_text())["stdio"]
        cpu = (evidence["v03"]["loaded_elbow"]["run"] if scenario == "loaded_elbow" else evidence["v04"]["tracking"]["run"] if scenario == "elbow_tracking" else evidence["v05"][scenario]["run"])
        assert data["run"]["artifacts"]["series.csv"]["sha256"] == cpu["artifacts"]["series.csv"]["sha256"]
        data["cpu_csv_hash_matches"] = True
    data["result_store"] = str(store.relative_to(ROOT))
    (ROOT / "reports" / filename).write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"status": "pass", "scenario": scenario, "physics_backend": "cpu", "render_backend": "nvidia_egl",
                      "device": data["run"]["render"]["gl_renderer"]}))


def main():
    exercise("loaded_elbow", "gpu.json")
    exercise("elbow_tracking", "gpu-tracking.json")
    exercise("standing_contact_probe", "gpu-contact.json")
    exercise("assisted_stance", "gpu-assisted.json")


if __name__ == "__main__":
    main()
