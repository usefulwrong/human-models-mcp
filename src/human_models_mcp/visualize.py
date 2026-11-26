"""Standalone public render toolkit; shares the typed API with MCP, without an LLM."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

from .rendering import get_render_artifact, get_render_job, list_render_profiles, render_result
from .research import DEFAULT_RESEARCH_SCENARIO, ResearchRequest, run_research


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
    evidence_link = (' · <a href="evidence.json">Evidence Contract</a>'
                     if "evidence.json" in job["artifacts"] else "")
    (destination / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>UsefulWrong computed motion</title><h1>UsefulWrong / saved-state visualization</h1><video controls loop src="animation.mp4" style="max-width:100%"></video><p>Computed model motion, Blender presentation. No clinical or balance validation.</p><img src="preview.png" style="max-width:100%"><p><a href="passport.json">Scientific passport</a>'
        + evidence_link
        + ' · <a href="source.zip">Original numeric data</a> · <a href="scene.blend">Editable Blender scene</a> · <a href="frames.json">Frame clock and hashes</a></p>'
    )
    print("Open render: " + str(destination / "index.html"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-profiles")
    render = sub.add_parser("render")
    render.add_argument("--run-id", required=True)
    render.add_argument("--profile", choices=["preview", "scientific", "cinematic"])
    render.add_argument("--recipe", choices=list(list_render_profiles()["recipes"]))
    render.add_argument("--layers", nargs="+", default=None)
    render.add_argument("--frames", type=int, default=21)
    render.add_argument("--fps", type=int)
    render.add_argument("--device", choices=["cpu", "gpu", "auto"], default=None)
    render.add_argument("--camera-view", choices=["full_body", "hands", "lumbar", "abdomen", "chest"])
    render.add_argument("--wait", action="store_true")
    render.add_argument("--output", type=Path)
    status = sub.add_parser("status")
    status.add_argument("job_id")
    download = sub.add_parser("download")
    download.add_argument("job_id")
    download.add_argument("--output", type=Path, required=True)
    evidence = sub.add_parser("evidence")
    evidence.add_argument("run_id")
    evidence.add_argument("--claim-id")
    research = sub.add_parser("research")
    research.add_argument("--scenario", default=DEFAULT_RESEARCH_SCENARIO)
    research.add_argument("--parameters", default="{}", help="JSON object with scenario overrides")
    research.add_argument("--recipe", choices=list(list_render_profiles()["recipes"]), action="append")
    research.add_argument("--options", default="{}", help="JSON object with render overrides")
    research.add_argument("--idempotency-key")
    atlas = sub.add_parser("provision-atlas")
    atlas.add_argument("--accept-license", required=True)
    atlas.add_argument("--offline", action="store_true")
    atlas.add_argument("--source-dir", type=Path)
    rectus = sub.add_parser("provision-rectus")
    rectus.add_argument("--accept-license", required=True)
    rectus.add_argument("--source", type=Path, required=True)
    compare = sub.add_parser("compare-fit3d")
    compare.add_argument("run_id")
    compare.add_argument("--dataset-json", type=Path)
    compare.add_argument("--metadata", type=Path)
    compare.add_argument("--private-output", type=Path)
    compare.add_argument("--accept-fit3d-terms", action="store_true")
    args = parser.parse_args()
    if args.command == "list-profiles":
        result = list_render_profiles()
    elif args.command == "research":
        try:
            request = ResearchRequest(scenario_id=args.scenario, parameters=json.loads(args.parameters),
                                      options=json.loads(args.options), idempotency_key=args.idempotency_key,
                                      **({"recipes": args.recipe} if args.recipe else {}))
            result = run_research(request)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.command == "evidence":
        from .evidence import get_evidence
        result = get_evidence(args.run_id, args.claim_id)
    elif args.command == "provision-atlas":
        from .atlas import provision_atlas
        try:
            result = provision_atlas(args.accept_license, args.offline, args.source_dir)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == "provision-rectus":
        from .rectus import provision_rectus
        try:
            result = provision_rectus(args.accept_license, args.source)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == "compare-fit3d":
        from .reference_motion import write_comparison
        if args.dataset_json and not (args.metadata and args.private_output):
            parser.error("a dataset requires --metadata and --private-output")
        try:
            result = write_comparison(args.run_id, args.dataset_json,
                                      json.loads(args.metadata.read_text()) if args.metadata else None,
                                      args.private_output, args.accept_fit3d_terms)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == "status":
        result = get_render_job(args.job_id)
    elif args.command == "download":
        result = get_render_job(args.job_id)
        if result.get("status") != "completed":
            raise RuntimeError("render is not completed: " + str(result))
        export(result, args.output)
    else:
        options = {"frames": args.frames}
        if args.fps is not None:
            options["fps"] = args.fps
        if args.camera_view:
            options["camera_view"] = args.camera_view
        if args.device:
            options["device"] = args.device
        result = render_result(args.run_id, args.profile, args.layers, options, recipe=args.recipe)
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
    if "error" in result or result.get("status") in {"failed", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
