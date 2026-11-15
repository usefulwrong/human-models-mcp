"""Create real named render exports; uses the independently exercised public SDK client."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if args.preview:
        store = ROOT / "reports/e2e-client-runs" / ("v06-preview-" + str(uuid4()))
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
                "pushup_palms",
                "--output",
                str(physical),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        run_id = json.loads((physical / "client.json").read_text())["run"]["run_id"]
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/visualize.py"),
                "render",
                "--run-id",
                run_id,
                "--profile",
                "preview",
                "--frames",
                "5",
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
        return
    evidence = json.loads((ROOT / "reports/V06_RENDER_GPU.json").read_text())
    if evidence["status"] != "pass":
        raise RuntimeError("actual GPU render E2E must pass before publishing demo subset")
    destination = ROOT / "docs/demo_v06"
    destination.mkdir(exist_ok=True)
    for name, case in evidence["cases"].items():
        source = ROOT / case["output"]
        out = destination / name
        out.mkdir(exist_ok=True)
        for filename in (
            "preview.png",
            "animation.gif",
            "animation.mp4",
            "passport.json",
            "frames.json",
            "geometry_validation.json",
            "source.zip",
        ):
            shutil.copy2(source / filename, out / filename)
    (destination / "index.html").write_text(
        """<!doctype html><meta charset="utf-8"><title>UsefulWrong / computed motion</title><style>body{background:#101923;color:#e3eaf0;font:16px system-ui;max-width:1100px;margin:2em auto}a{color:#63ccd5}video{width:100%}button{padding:.7em;margin:.3em}</style><h1>UsefulWrong / computed motion</h1><p>Two presentations of one elbow_tracking run. Same source states and fixed camera. Materials and lighting are presentation, not tissue parameters.</p><button onclick="switchView('elbow_tracking-scientific')">Scientific / activation paths + axes</button><button onclick="switchView('elbow_tracking-cinematic')">Cinematic / native geometry + paths</button><video id="elbow" controls loop src="elbow_tracking-scientific/animation.mp4"></video><p><a id="passport" href="elbow_tracking-scientific/passport.json">Scientific passport</a> · <a href="elbow_tracking-scientific/source.zip">Original source states and numeric data</a></p><h2>Externally assisted contact transient</h2><p>Explicit pelvis PD support; no unassisted human balance claim. GRF and external support are separate.</p><video controls loop src="assisted_stance-scientific/animation.mp4"></video><p><a href="assisted_stance-scientific/passport.json">Contact passport</a> · <a href="assisted_stance-scientific/source.zip">Contact source data</a></p><script>function switchView(name){let v=document.getElementById('elbow'),t=v.currentTime,playing=!v.paused;v.src=name+'/animation.mp4';v.addEventListener('loadedmetadata',()=>{v.currentTime=Math.min(t,v.duration);if(playing)v.play()},{once:true});document.getElementById('passport').href=name+'/passport.json'}</script>"""
    )
    (ROOT / "reports/V06_DEMO.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "source_evidence": "reports/V06_RENDER_GPU.json",
                "directory": "docs/demo_v06",
                "source_runs": {k: v["run_id"] for k, v in evidence["cases"].items()},
                "note": "Demo subset copied from verified actual Cycles output; full editable scenes and all frames remain in named E2E exports",
            },
            indent=2,
        )
        + "\n"
    )
    print("Open demo:", destination / "index.html")


if __name__ == "__main__":
    main()
