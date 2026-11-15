"""Real worker/process failure tests on isolated jobs; fault injection is explicitly labeled."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main():
    store = ROOT / "reports/e2e-client-runs" / ("v06-fault-science-" + str(uuid4()))
    store.mkdir(parents=True)
    env = {**os.environ, "HMM_RESULTS_DIR": str(store)}
    dc = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "compose.render-gpu.yaml"),
        "-p",
        "human-models-mcp-night",
    ]
    subprocess.run([*dc, "stop", "renderer"], env=env, check=True)
    source = StdioServerParameters(
        command="docker",
        args=[
            "compose",
            "-f",
            str(ROOT / "compose.yaml"),
            "-p",
            "human-models-mcp-night",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "runtime",
        ],
        env={"HMM_RESULTS_DIR": str(store)},
        cwd=str(ROOT),
    )
    evidence = {}
    async with Client(source, read_timeout_seconds=120) as client:

        async def call(name, args):
            response = await client.call_tool(name, args)
            assert not response.is_error, response.content
            return response.structured_content

        run = await call("run_scenario", {"scenario_id": "elbow_tracking", "parameters": {"render": False}})
        assert run["status"] == "computed"
        baseline = (store / run["run_id"] / "manifest.json").read_bytes()

        async def submit(options=None):
            job = await call(
                "render_result",
                {
                    "run_id": run["run_id"],
                    "layers": ["bones"],
                    "options": {
                        "frames": 3,
                        "width": 320,
                        "height": 180,
                        "samples": 1,
                        "device": "cpu",
                        **(options or {}),
                    },
                },
            )
            assert job["status"] == "queued", job
            return job

        for fault in (
            "corrupt_source",
            "missing_source",
            "missing_models",
            "incompatible_source_engine",
            "incompatible_source_model",
            "blender_crash",
            "timeout",
            "gpu_oom",
        ):
            job = await submit(
                {"timeout_s": 30} if fault == "timeout" else {"device": "gpu"} if fault == "gpu_oom" else {}
            )
            folder = ROOT / "render_jobs" / job["job_id"]
            args = []
            if fault in ("incompatible_source_engine", "incompatible_source_model"):
                manifest = folder / "input/manifest.json"
                changed = json.loads(manifest.read_text())
                if fault == "incompatible_source_engine":
                    changed["engine"]["version"] = "0.0.0"
                else:
                    changed["model"]["asset_sha256"] = "0" * 64
                manifest.write_text(json.dumps(changed))
                record = json.loads((folder / "job.json").read_text())
                record["source_files"]["manifest.json"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
                (folder / "job.json").write_text(json.dumps(record))
            if fault == "corrupt_source":
                (folder / "input/trajectory.npz").write_bytes(b"corrupt input")
            if fault == "missing_source":
                (folder / "input/series.csv").rename(folder / "input/series.missing")
            if fault == "missing_models":
                empty = ROOT / "reports/logs" / ("v06-empty-models-" + str(uuid4()))
                empty.mkdir()
                args += ["-v", str(empty) + ":/app/models/ms_human_700:ro"]
            inject = {"blender_crash": "crash", "timeout": "timeout", "gpu_oom": "oom"}.get(fault)
            if inject:
                args += ["-e", "HMM_TEST_RENDER_FAILURE=" + inject]
            started = time.monotonic()
            worker = subprocess.run(
                [*dc, "run", "--rm", "--no-deps", "-T", *args, "renderer", "--once"],
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            record = await call("get_render_job", {"job_id": job["job_id"]})
            if fault == "gpu_oom":
                assert record["status"] == "completed", record
                passport = json.loads((folder / "artifacts/passport.json").read_text())
                assert passport["fallback"] and "injected GPU out of memory" in passport["fallback"]["reason"]
                assert passport["renderer"]["device"]["backend"] == "cpu"
            else:
                assert record["status"] == "failed" and record.get("error", {}).get("message"), record
                if fault == "timeout":
                    assert record["error"]["code"] == "timeout"
                if fault == "blender_crash":
                    assert record["error"]["code"] == "render_failed"
                if fault.startswith("incompatible_source_"):
                    assert "incompatible source" in record["error"]["message"]
            assert (await call("get_result", {"run_id": run["run_id"]})) == run
            assert (store / run["run_id"] / "manifest.json").read_bytes() == baseline
            evidence[fault] = {
                "status": "pass",
                "expected_render_state": record["status"],
                "error": record.get("error"),
                "job_id": job["job_id"],
                "worker_exit_code": worker.returncode,
                "seconds": time.monotonic() - started,
                "injection": inject,
                "source_physics_unchanged": True,
            }
        # Actual container/Blender interruption, after a genuine first Cycles frame.
        job = await submit({"frames": 101, "width": 960, "height": 540, "samples": 32})
        subprocess.run([*dc, "up", "-d", "--no-deps", "renderer"], env=env, check=True)
        folder = ROOT / "render_jobs" / job["job_id"]
        deadline = time.monotonic() + 180
        while not (folder / "work/raw_0000.png").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("no actual first frame before interruption")
            await asyncio.sleep(0.5)
        subprocess.run([*dc, "kill", "-s", "SIGKILL", "renderer"], env=env, check=True)
        record = await call("get_render_job", {"job_id": job["job_id"]})
        assert record["status"] == "failed" and record["error"]["code"] == "interrupted", record
        evidence["interrupted_blender"] = {
            "status": "pass",
            "job_id": job["job_id"],
            "error": record["error"],
            "real_first_frame_present": True,
            "source_physics_unchanged": (await call("get_result", {"run_id": run["run_id"]})) == run,
        }
        subprocess.run([*dc, "up", "-d", "--no-deps", "renderer"], env=env, check=True)
        assert (await call("get_render_job", {"job_id": job["job_id"]}))["status"] == "failed"
        evidence["restart_persistence"] = {"status": "pass", "job_id": job["job_id"]}
    result = {
        "status": "pass",
        "cases": evidence,
        "physical_gpu_exhaustion": "not_forced; controlled MemoryError after actual GPU enumeration proves retry path, followed by real CPU render",
        "run_id": run["run_id"],
        "source_manifest_sha256": hashlib.sha256(baseline).hexdigest(),
    }
    (ROOT / "reports/V06_RENDER_FAILURES.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
