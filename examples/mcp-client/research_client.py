"""Exercise the complete push-up workflow with the official MCP SDK."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic

from mcp import Client, StdioServerParameters

from render_artifacts import download

ROOT = Path(__file__).resolve().parents[2]
RECIPES = ["pushup_scientific", "pushup_muscle_paths", "pushup_rectus", "pushup_cinematic"]


def payload_size(value):
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key", default="research-flat-palm")
    parser.add_argument("--frames", type=int, default=61)
    parser.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    options = {"width": 720, "height": 406, "samples": 4, "frames": args.frames,
               "device": args.device, "timeout_s": 900}
    if args.frames == 61:
        options["fps"] = 14
    basic = {"scenario_id": "pushup_flat_palm", "idempotency_key": args.key}
    source = StdioServerParameters(
        command="docker", args=["compose", "run", "--rm", "--no-deps", "-T", "runtime"],
        cwd=str(ROOT),
        env={key: val for key, val in os.environ.items() if key.startswith(("HMM_", "COMPOSE_"))},
    )
    trace = []
    async with Client(source, read_timeout_seconds=120) as client:
        async def call(tool, arguments):
            response = await client.call_tool(tool, arguments)
            assert not response.is_error and response.structured_content is not None, response.content
            result = response.structured_content
            trace.append({"tool": tool, "argument_bytes": payload_size(arguments), "result_bytes": payload_size(result)})
            return result

        submission = await call("run_scenario", {**basic, "visualization": {"recipes": RECIPES, "options": options}})
        assert submission["status"] == "submitted", submission
        assert submission["computed_status"] == "completed"
        assert submission["acceptance"]["muscle_driven"] == "NOT_ACHIEVED"
        assert submission["human_safety_status"] == "unsupported"
        run_id = submission["run_id"]
        separate = await call("run_scenario", basic)
        assert separate["run_id"] == run_id
        gate = await call("get_result", {"run_id": run_id, "claim_id": "gate:muscle_driven"})
        assert gate["acceptance"] == submission["acceptance"]
        for recipe, job in submission["render_jobs"].items():
            replay = await call("render_result", {"run_id": run_id, "recipe": recipe, "options": options})
            assert replay["job_id"] == job["job_id"], replay
        counts = {}
        for label, calls in (("combined", trace[:1]), ("separate", trace[1:])):
            counts[label] = {"tool_calls": len(calls), "argument_bytes": sum(c["argument_bytes"] for c in calls),
                             "result_bytes": sum(c["result_bytes"] for c in calls)}
        (args.output / "calls.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8", newline="\n")
        unsupported = await call("get_result", {"run_id": run_id, "claim_id": "computed_muscle_strain"})
        assert unsupported["status"] == "unsupported"
        manifest_digests = {k: v["sha256"] for k, v in separate["artifacts"].items()}
        frame_reference = None
        deadline = monotonic() + 3900
        for recipe, pending in submission["render_jobs"].items():
            job_id = pending["job_id"]
            while True:
                job = await call("get_render_job", {"job_id": job_id})
                if job["status"] not in {"queued", "running"}:
                    break
                if monotonic() >= deadline:
                    raise TimeoutError("render worker stalled or exceeded the workflow budget")
                await asyncio.sleep(10)
            assert job["status"] == "completed", job
            assert job["render_backend"]["backend"] in ({"cpu"} if args.device == "cpu" else {"optix", "cuda"})
            assert job["scientific"]["acceptance"] == gate["acceptance"]
            dest = args.output / recipe
            artifact_ids = ["start.png", "bottom.png", "return.png", "preview.png", "animation.mp4", "animation.gif",
                            "plot.png", "frames.json", "passport.json", "evidence.json"]
            if recipe == "pushup_rectus":
                artifact_ids += ["anatomy_registration.json", "scene.zip", "scene.blend", "source.zip", "frames.zip"]
            receipts = {name: await download(client, job_id, name, dest / name) for name in artifact_ids}
            (dest / "client.json").write_text(json.dumps({"job": job, "downloads": receipts}, indent=2) + "\n", encoding="utf-8", newline="\n")
            clock = json.loads((dest / "frames.json").read_text(encoding="utf-8"))
            keys = ("source_index", "time_s", "state_sha256")
            current = [tuple(f[k] for k in keys) for f in clock["frames"]]
            assert frame_reference is None or current == frame_reference
            frame_reference = current
            evidence = json.loads((dest / "evidence.json").read_text(encoding="utf-8"))
            assert evidence["run_id"] == run_id and evidence["acceptance"] == gate["acceptance"]
            assert evidence["human_safety_status"] == "unsupported"
            if recipe == "pushup_rectus":
                anatomy = json.loads((dest / "anatomy_registration.json").read_text(encoding="utf-8"))
                assert anatomy["status"] == "illustrative" and set(anatomy["structures"]) == {"r", "l"}
                assert anatomy["source"]["license"] == "CC-BY-SA-4.0"
        original = await call("get_result", {"run_id": run_id})
        assert {k: v["sha256"] for k, v in original["artifacts"].items()} == manifest_digests
    (args.output / "status.json").write_text(json.dumps({"status": "PASS", "run_id": run_id, "calls": trace}, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    asyncio.run(main())
