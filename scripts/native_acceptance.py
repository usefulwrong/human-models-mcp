"""Exercise the installed release through the official MCP SDK."""

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import Client, StdioServerParameters

from human_models_mcp.runtime.processes import managed_process

SCENARIOS = (
    "elbow_sweep", "knee_coupled", "activation_pulse", "loaded_elbow", "elbow_tracking",
    "wrist_benchmark", "standing_contact_probe", "assisted_stance", "pushup_flat_palm",
)
ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


async def call(client, name, **arguments):
    reply = await client.call_tool(name, arguments)
    assert not reply.is_error, (name, reply.content)
    assert isinstance(reply.structured_content, dict), name
    return reply.structured_content


async def science(directory, env, short=False):
    source = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "human_models_mcp"],
                                  cwd=str(ROOT), env=env)
    evidence = {}
    async with Client(source, read_timeout_seconds=120) as client:
        assert {"list_scenarios", "run_scenario", "get_result", "get_contact", "get_artifact"} <= {
            tool.name for tool in (await client.list_tools()).tools
        }
        listed = {item["id"]: item for item in (await call(client, "list_scenarios"))["scenarios"]}
        for name in ("elbow_sweep",) if short else SCENARIOS:
            started = time.monotonic()
            parameters = {"render": False} if listed[name]["defaults"].get("render") else {}
            args = {"scenario_id": name, "parameters": parameters, "idempotency_key": f"acceptance-{directory.name[:60]}-{name}"}
            run = await call(client, "run_scenario", **args)
            assert run["status"] == "computed", run
            assert run == await call(client, "get_result", run_id=run["run_id"])
            assert run == await call(client, "run_scenario", **args)
            assert run["engine"]["version"] == "3.17.0"
            assert run["execution"]["physics_backend"] == "cpu" and run["execution"]["render_backend"] == "none"
            assert run["counts"]["actuators"] == (100 if name in SCENARIOS[6:8] else 700)
            assert run["scientific"]["validation_level"] == "numerical_sanity"
            for artifact_name, metadata in run["artifacts"].items():
                artifact = await call(client, "get_artifact", run_id=run["run_id"], artifact_id=artifact_name)
                assert artifact["status"] == "ok", artifact_name
                data = base64.b64decode(artifact["data"], validate=True) if artifact["encoding"] == "base64" else artifact["data"].encode("utf-8")
                assert len(data) == metadata["bytes"] and hashlib.sha256(data).hexdigest() == metadata["sha256"]
            checks = run["scientific"].get("checks", [])
            acceptance = run["scientific"].get("acceptance", {})
            if name == "pushup_flat_palm":
                assert acceptance["full_pushup"] == "FAIL" and acceptance["human_experimental_validation"] == "NOT_VALIDATED"
                contact = await call(client, "get_contact", run_id=run["run_id"], part="hand_r", sample=55)
                assert contact["status"] == "ok", contact
            else:
                assert checks and all(check["status"] == "pass" for check in checks), (name, checks)
            unsafe = await call(client, "get_artifact", run_id=run["run_id"], artifact_id="series.csv:stream")
            assert unsafe["status"] == "invalid_input"
            execution = run["execution"]
            evidence[name] = {"run_id": run["run_id"], "elapsed_s": round(time.monotonic() - started, 3),
                              "model_sha256": run["model"]["asset_sha256"], "metrics": run["outputs"]["metrics"],
                              "timeseries": run["outputs"]["time_series"], "engine": run["engine"],
                              "checks": checks, "acceptance": acceptance, "counts": run["counts"],
                              "timestep_s": execution["timestep_s"], "integration_steps": execution["integration_steps"],
                              "validation_sha256": run["artifacts"]["validation.json"]["sha256"]}
            write(directory / "science.json", evidence)
            print(f"{name}: computed, {acceptance.get('full_pushup','numerical checks passed')}", flush=True)
    return evidence


async def http(directory, env):
    endpoint = "http://127.0.0.1:8765/mcp"
    command = [sys.executable, "-X", "utf8", "-m", "human_models_mcp", "--transport", "http"]
    with (directory / "http.log").open("wb") as log, managed_process(
        command, linux_group=True, memory=5 * 1024**3, env=env, stdin=subprocess.DEVNULL,
        stdout=log, stderr=subprocess.STDOUT,
    ) as server:
        for _ in range(120):
            assert server.poll() is None, "HTTP server exited"
            try:
                with socket.create_connection(("127.0.0.1", 8765), timeout=.2):
                    break
            except OSError:
                await asyncio.sleep(.25)
        else:
            raise TimeoutError("HTTP server did not bind loopback")
        for headers in ({"Origin": "https://untrusted.invalid"}, {"Host": "untrusted.invalid"}):
            try:
                with urlopen(Request(endpoint, data=b"{}", headers={**headers, "Content-Type": "application/json"}), timeout=5):
                    raise AssertionError(f"HTTP transport accepted {headers}")
            except HTTPError as exc:
                assert exc.code in ({403} if "Origin" in headers else {400, 403, 421}), exc.code
        async with Client(endpoint, read_timeout_seconds=120) as client:
            assert any(tool.name == "list_scenarios" for tool in (await client.list_tools()).tools)
            assert (await call(client, "list_scenarios"))["scenarios"]
    return {"endpoint": endpoint, "host_and_origin_rejected": True}


async def render(directory, env, run):
    from native import renderer_env
    from human_models_mcp.rendering import MAX_CHUNK

    source = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "human_models_mcp"],
                                  cwd=str(ROOT), env=env)
    async with Client(source, read_timeout_seconds=120) as client:
        args = {"run_id": run, "profile": "preview", "options": {"frames": 3, "device": "cpu"},
                "idempotency_key": "native-acceptance-render"}
        first, second = await asyncio.gather(*(call(client, "render_result", **args) for _ in range(2)))
        job = first["job_id"]
        assert second["job_id"] == job
        command = [sys.executable, "-X", "utf8", "-m", "human_models_mcp.render_worker", "--once"]
        with (directory / "renderer.log").open("wb") as log, managed_process(
            command, linux_group=True, memory=10 * 1024**3, env={**renderer_env(), **env},
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        ) as worker:
            assert worker.wait(timeout=240) == 0, "renderer failed"
        result = await call(client, "get_render_job", job_id=job)
        assert result["status"] == "completed", result
        artifacts = ["preview.png", "animation.gif", "animation.mp4", "scene.blend",
                     "scene.zip", "source.zip", "frames.zip", "frames.json", "passport.json"]
        for artifact in artifacts:
            offset = 0
            with (directory / artifact).open("xb") as stream:
                while True:
                    part = await call(client, "get_render_artifact", job_id=job,
                                      artifact_id=artifact, offset=offset, length=MAX_CHUNK)
                    assert part["status"] == "ok" and part["offset"] == offset, part
                    data = base64.b64decode(part["data"], validate=True)
                    assert hashlib.sha256(data).hexdigest() == part["chunk_sha256"]
                    stream.write(data)
                    offset += len(data)
                    if part["eof"]:
                        break
            assert offset == result["artifacts"][artifact]["bytes"]
            with (directory / artifact).open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == result["artifacts"][artifact]["sha256"]
        from PIL import Image
        for name in ("preview.png", "animation.gif"):
            with Image.open(directory / name) as image:
                image.verify()
        tools = renderer_env()
        ffmpeg = Path(tools.get("HMM_FFMPEG", "ffmpeg"))
        ffprobe = ffmpeg.with_name("ffprobe" + ffmpeg.suffix)
        probe = subprocess.check_output(
            [str(ffprobe), "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
             "stream=nb_read_frames,width,height,duration", "-of", "json", str(directory / "animation.mp4")],
            encoding="utf-8", timeout=30)
        stream = json.loads(probe)["streams"][0]
        options = result["request"]["options"]
        assert int(stream["nb_read_frames"]) == options["frames"] == 3
        assert (stream["width"], stream["height"]) == (options["width"], options["height"])
        assert abs(float(stream["duration"]) - options["frames"] / options["fps"]) < .01
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/verify_visual_native.py"),
                        str(directory)], env=env, check=True, timeout=120)
        subprocess.run([tools.get("BLENDER_BIN", "/opt/blender/blender"), "-b", "--factory-startup",
                        "--python-exit-code", "1", "--python", str(ROOT / "scripts/verify_visual_blend.py"),
                        "--", str(directory)], check=True, timeout=120)
        return {"job_id": job, "media": stream, "status": "completed",
                "native": json.loads((directory / "independent-native.json").read_bytes())["status"],
                "reopened_blend": json.loads((directory / "independent-blend.json").read_bytes())["status"]}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--renderer", action="store_true")
    parser.add_argument("--short", action="store_true")
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "HUMAN_MODELS_HOME": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    started = time.monotonic()
    results = await science(args.report, env, args.short)
    record = {"status": "PASS", "platform": platform.platform(), "python": platform.python_version(),
              "timestamp": datetime.now(timezone.utc).isoformat(), "http": await http(args.report, env)}
    if args.renderer:
        record["render"] = await render(args.report, env, results["elbow_tracking"]["run_id"])
    record["elapsed_s"] = round(time.monotonic() - started, 3)
    write(args.report / "acceptance.json", record)
    print("NATIVE_SDK_ACCEPTANCE_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
