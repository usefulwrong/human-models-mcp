"""Independent official-SDK simulation -> queued Blender -> verified media client."""

import argparse
import hashlib
import asyncio
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time

from mcp import Client, StdioServerParameters
from PIL import Image, ImageStat
from render_artifacts import download


async def exercise(client, args):
    calls = []
    response_bytes = {}

    async def call(name, arguments=None):
        response = await client.call_tool(name, arguments or {})
        if response.is_error or response.structured_content is None:
            raise RuntimeError(str(response.content))
        value = response.structured_content
        response_bytes[name] = response_bytes.get(name, 0) + len(json.dumps(value, separators=(",", ":")).encode())
        calls.append({"tool": name, "arguments": arguments or {}, "status": value.get("status", "metadata")})
        return value

    tools = {t.name for t in (await client.list_tools()).tools}
    assert len(tools) == 14 and {"render_result", "get_render_artifact", "run_scenario"} <= tools
    profiles = await call("list_render_profiles")
    assert set(profiles["profiles"]) == {"preview", "scientific", "cinematic"}
    scenarios = await call("list_scenarios")
    assert args.scenario in {s["id"] for s in scenarios["scenarios"]}
    scenario = await call("describe_scenario", {"scenario_id": args.scenario})
    card = await call("describe_model", {"model_id": scenario["model"]})
    assert card["status"] == "available"
    run = (
        await call("get_result", {"run_id": args.run_id})
        if args.run_id
        else await call("run_scenario", {"scenario_id": args.scenario, "parameters": {"render": False}})
    )
    assert run["status"] == "computed" and run["scenario_id"] == args.scenario
    source_before = run["artifacts"]["trajectory.npz"]["sha256"]
    layers = (
        ["bones", "muscle_paths", "joint_axes", "contact_forces", "center_of_mass"]
        if args.scenario in ("pushup", "pushup_palms", "pushup_knuckles") else
        ["bones", "muscle_paths", "joint_axes", "applied_moments"]
        if args.scenario in ("elbow_tracking", "loaded_elbow")
        else ["bones", "contact_forces", "center_of_mass", "joint_axes", "applied_moments"]
    )
    if args.profile == "cinematic":
        layers = ["bones", "muscle_paths"]
    if args.layers:
        layers = args.layers
    options = {
        "frames": args.frames,
        "fps": args.fps,
        "device": args.device,
        "width": args.width,
        "height": args.height,
        "samples": args.samples,
        "timeout_s": args.timeout,
    }
    if args.camera_view:
        options["camera_view"] = args.camera_view
    request = {
        "run_id": run["run_id"],
        "profile": args.profile,
        "layers": layers,
        "options": options,
        "idempotency_key": hashlib.sha256(str(args.output).encode()).hexdigest(),
    }
    if args.recipe:
        request.pop("layers")
        request["recipe"] = args.recipe
    start = time.monotonic()
    job = await call("render_result", request)
    assert job["status"] in ("queued", "running", "completed"), job
    duplicate = await call("render_result", request)
    assert duplicate["job_id"] == job["job_id"]
    assert (await call("render_result", {"run_id": run["run_id"], "layers": ["internal_organs"]}))[
        "status"
    ] == "unsupported"
    assert (await call("render_result", {"run_id": run["run_id"], "options": {"script": "untrusted.py"}}))[
        "status"
    ] == "invalid_input"
    assert (await call("get_render_artifact", {"job_id": job["job_id"], "artifact_id": "../../etc/passwd"}))[
        "status"
    ] == "invalid_input"
    assert (
        await call(
            "get_render_artifact", {"job_id": job["job_id"], "artifact_id": "preview.png", "length": 300000}
        )
    )["status"] == "invalid_input"
    while job["status"] in ("queued", "running"):
        if time.monotonic() - start > 1000:
            raise TimeoutError("render worker did not finish")
        await asyncio.sleep(1)
        job = await call("get_render_job", {"job_id": job["job_id"]})
    assert job["status"] == "completed", job
    args.output.mkdir(parents=True, exist_ok=False)
    transfers = {}
    for name in (
        *[name for name in ("evidence.json", "anatomy_registration.json") if name in job["artifacts"]],
        "preview.png",
        "animation.mp4",
        "animation.gif",
        "frames.json",
        "passport.json",
        "geometry_validation.json",
        "source.zip",
        "scene.zip",
        "scene.blend",
        "frames.zip",
        "plot.png",
    ):
        transfers[name] = await download(client, job["job_id"], name, args.output / name)
        assert transfers[name]["sha256"] == job["artifacts"][name]["sha256"]
    with Image.open(args.output / "preview.png") as image:
        assert (
            image.format == "PNG"
            and image.size == (args.width, args.height)
            and max(ImageStat.Stat(image).stddev) > 3
        )
    with Image.open(args.output / "animation.gif") as image:
        assert image.n_frames == args.frames
    video = (args.output / "animation.mp4").read_bytes()
    assert b"ftyp" in video[:32]
    passport = json.loads((args.output / "passport.json").read_text())
    frames = json.loads((args.output / "frames.json").read_text())
    assert len(frames["frames"]) == args.frames and frames["source_files"]["trajectory.npz"] == source_before
    assert all(a["time_s"] < b["time_s"] for a, b in zip(frames["frames"], frames["frames"][1:]))
    assert passport["source_run_id"] == run["run_id"] and passport["renderer"]["physics"] == "not_executed"
    assert (
        passport["geometry_validation"]["imported_usd"]["status"]
        == passport["geometry_validation"]["baked_blend"]["status"]
        == "pass"
    )
    if "evidence.json" in transfers:
        evidence = json.loads((args.output / "evidence.json").read_text())
        claims = {claim["claim_id"]: claim["value"] for claim in evidence["claims"]}
        assert claims == {"artifact:" + name: value for name, value in job["artifacts"].items()
                          if name != "evidence.json"}
    if "anatomy_registration.json" in transfers:
        assert passport["anatomy"]["external_registration"] == "illustrative"
        assert passport["anatomy"]["atlas_license"] == "CC-BY-SA-2.1-JP"
        assert "FMA34690" in passport["anatomy"]["source"]
        atlas = json.loads((args.output / "anatomy_registration.json").read_text())
        assert atlas["blender"]["status"] == "PASS" and len(atlas["frames"]) == args.frames
        assert set(atlas["phase_source_indices"].values()) <= {f["source_index"] for f in frames["frames"]}
        assert any(c["anatomical_mapping_status"] == "illustrative" for c in evidence["claims"])
        claim = await call("get_result", {"run_id": run["run_id"], "claim_id": "artifact:trajectory.npz"})
        assert claim["run_id"] == run["run_id"] and claim["claims"][0]["value"]["sha256"] == source_before
        rejected = await call("get_result", {"run_id": run["run_id"], "claim_id": "computed_muscle_strain"})
        assert rejected["status"] == "unsupported"
    else:
        assert passport["anatomy"]["external_registration"] == "registration_unverified"
    if args.scenario in ("pushup", "pushup_palms", "pushup_knuckles"):
        assert passport["source_scientific"]["acceptance"] == run["scientific"]["acceptance"]
    after = await call("get_result", {"run_id": run["run_id"]})
    assert after == run
    result = {
        "status": "pass",
        "transport": args.transport,
        "scenario": args.scenario,
        "run": run,
        "job": job,
        "source_physics_unchanged": True,
        "transfers": transfers,
        "calls": calls,
        "structured_response_bytes_excluding_artifact_chunks": response_bytes,
        "seconds": time.monotonic() - start,
        "output": str(args.output),
    }
    evidence_link = (' · <a href="evidence.json">Evidence Contract</a>'
                     if "evidence.json" in transfers else "")
    (args.output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>UsefulWrong computed motion</title><h1>UsefulWrong / saved-state visualization</h1><video controls loop src="animation.mp4" style="max-width:100%"></video><p>Computed model motion; Blender presentation. No clinical or balance validation.</p><img src="preview.png" style="max-width:100%"><p><a href="passport.json">Scientific passport</a>'
        + evidence_link
        + ' · <a href="source.zip">Source data</a> · <a href="scene.blend">Editable scene</a> · <a href="frames.json">Frame clock and hashes</a></p>'
    )
    (args.output / "client.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "pass",
                "scenario": args.scenario,
                "run_id": run["run_id"],
                "job_id": job["job_id"],
                "output": str(args.output),
                "seconds": result["seconds"],
            }
        ),
        flush=True,
    )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="elbow_tracking")
    parser.add_argument("--run-id")
    parser.add_argument("--profile", default="preview")
    parser.add_argument("--recipe")
    parser.add_argument("--layers", nargs="+")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--fps", type=int, default=6)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=270)
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--camera-view", choices=["full_body", "hands", "lumbar", "abdomen", "chest"])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=["docker", "stdio", "http"], default="docker")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.transport == "docker":
        source = StdioServerParameters(
            command="docker",
            args=[
                "compose",
                "-f",
                str(root / "compose.yaml"),
                "-p",
                os.environ.get("COMPOSE_PROJECT_NAME", "human-models-mcp-night"),
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "runtime",
            ],
            cwd=str(root),
            env={key: os.environ[key] for key in ("HMM_RESULTS_DIR", "HMM_RUNTIME_IMAGE", "HMM_RENDER_IMAGE", "COMPOSE_PROJECT_NAME", "HMM_UID", "HMM_GID") if key in os.environ},
        )
        async with Client(source, read_timeout_seconds=120) as client:
            await exercise(client, args)
    elif args.transport == "stdio":
        async with Client(
            StdioServerParameters(command=sys.executable, args=["-m", "human_models_mcp"], env=dict(os.environ)),
            read_timeout_seconds=120,
        ) as client:
            await exercise(client, args)
    else:
        server = subprocess.Popen(
            [sys.executable, "-m", "human_models_mcp", "--transport", "http"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for attempt in range(100):
                if server.poll() is not None:
                    raise RuntimeError("HTTP MCP server exited before readiness")
                try:
                    with socket.create_connection(("127.0.0.1", 8765), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                raise TimeoutError("HTTP MCP startup timed out")
            async with Client("http://127.0.0.1:8765/mcp", read_timeout_seconds=120) as client:
                await exercise(client, args)
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
