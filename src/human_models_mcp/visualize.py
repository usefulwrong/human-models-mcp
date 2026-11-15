"""Standalone public render toolkit; shares the typed API with MCP, without an LLM."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

from .rendering import get_render_artifact, get_render_job, list_render_profiles, render_result


def export(job, destination):
    if destination.exists():
        raise FileExistsError("choose a new output directory")
    destination.mkdir(parents=True)
    for name, meta in job["artifacts"].items():
        offset = 0
        data = bytearray()
        while offset < meta["bytes"]:
            part = get_render_artifact(job["job_id"], name, offset)
            if part["status"] != "ok":
                raise ValueError(str(part))
            chunk = base64.b64decode(part["data"], validate=True)
            if hashlib.sha256(chunk).hexdigest() != part["chunk_sha256"]:
                raise ValueError("chunk hash differs")
            data.extend(chunk)
            offset = part["next_offset"]
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError("whole-file hash differs")
        (destination / name).write_bytes(data)
    (destination / "job.json").write_text(json.dumps(job, indent=2) + "\n")
    (destination / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>UsefulWrong computed motion</title><h1>UsefulWrong / saved-state visualization</h1><video controls loop src="animation.mp4" style="max-width:100%"></video><p>Computed model motion, Blender presentation. No clinical or balance validation.</p><img src="preview.png" style="max-width:100%"><p><a href="passport.json">Scientific passport</a> · <a href="source.zip">Original numeric data</a> · <a href="scene.blend">Editable Blender scene</a> · <a href="frames.json">Frame clock and hashes</a></p>'
    )
    print("Open render: " + str(destination / "index.html"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-profiles")
    render = sub.add_parser("render")
    render.add_argument("--run-id", required=True)
    render.add_argument("--profile", default="preview")
    render.add_argument("--layers", nargs="+", default=None)
    render.add_argument("--frames", type=int, default=21)
    render.add_argument("--device", choices=["cpu", "gpu", "auto"], default=None)
    render.add_argument("--camera-view", choices=["full_body", "hands", "lumbar", "abdomen", "chest"], default="full_body")
    render.add_argument("--wait", action="store_true")
    render.add_argument("--output", type=Path)
    status = sub.add_parser("status")
    status.add_argument("job_id")
    download = sub.add_parser("download")
    download.add_argument("job_id")
    download.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "list-profiles":
        result = list_render_profiles()
    elif args.command == "status":
        result = get_render_job(args.job_id)
    elif args.command == "download":
        result = get_render_job(args.job_id)
        if result.get("status") != "completed":
            raise RuntimeError("render is not completed: " + str(result))
        export(result, args.output)
    else:
        options = {"frames": args.frames, "camera_view": args.camera_view}
        if args.device:
            options["device"] = args.device
        result = render_result(args.run_id, args.profile, args.layers, options)
        if args.wait and result.get("job_id"):
            deadline = time.monotonic() + 1000
            while result["status"] in ("queued", "running"):
                if time.monotonic() > deadline:
                    raise TimeoutError("render worker absent, stalled or too slow; inspect job status")
                time.sleep(0.5)
                result = get_render_job(result["job_id"])
        if args.output:
            if result.get("status") != "completed":
                raise RuntimeError("use --wait to export a completed render")
            export(result, args.output)
    print(json.dumps(result, indent=2))
    if result.get("status") in ("failed", "invalid_input", "unsupported", "resource_limit"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
