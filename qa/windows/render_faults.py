"""Exercise the Windows renderer queue and actual Blender process cleanup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from native import renderer_env
from human_models_mcp.registry import home
from human_models_mcp.rendering import get_render_job, job_dir, read_job, render_result
from human_models_mcp.results import run_dir


def start(fault, log):
    return subprocess.Popen([sys.executable, "-X", "utf8", "-m", "human_models_mcp.render_worker", "--once"],
                            env={**renderer_env(), "HMM_TEST_RENDER_FAILURE": fault},
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


def queue(run_id, **settings):
    options = {"frames": 11, "device": "cpu", **settings}
    key = uuid4().hex
    request = render_result(run_id, "preview", options=options, idempotency_key=key)
    assert request["status"] == "queued", request
    assert render_result(run_id, "preview", options=options, idempotency_key=key)["job_id"] == request["job_id"]
    return request["job_id"]


def no_blender_for(job):
    command = ("Get-CimInstance -ClassName Win32_Process -Filter \"Name='blender.exe'\" | "
               f"Where-Object CommandLine -Match '{job}' | Select-Object -ExpandProperty ProcessId")
    for _ in range(15):
        out = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command],
                                      encoding="utf-8", timeout=10)
        if not out.strip():
            return
        time.sleep(.5)
    raise AssertionError("a Blender process from the interrupted test job survived")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    os.environ.setdefault("HUMAN_MODELS_HOME", str(Path(__file__).resolve().parents[2]))
    assert home().is_dir() and os.name == "nt"
    args.evidence.mkdir(parents=True, exist_ok=False)
    source = run_dir(args.run_id) / "manifest.json"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = {}
    for label, fault in (("blender_crash", "crash"), ("blender_timeout", "timeout")):
        job = queue(args.run_id, timeout_s=30 if fault == "timeout" else 120)
        started = time.monotonic()
        with (args.evidence / f"{label}.log").open("wb") as log, start(fault, log) as worker:
            try:
                assert worker.wait(timeout=140) == 0
            finally:
                if worker.poll() is None:
                    worker.kill()
        record = get_render_job(job)
        assert record["status"] == "failed", record
        assert record["error"]["code"] == ("timeout" if fault == "timeout" else "render_failed"), record
        no_blender_for(job)
        result[label] = {"job": job, "error": record["error"]["code"],
                         "duration_s": round(time.monotonic() - started, 3)}
    job = queue(args.run_id, frames=21, samples=8)
    started = time.monotonic()
    with (args.evidence / "owner-death.log").open("wb") as log, start("", log) as worker:
        try:
            frame = job_dir(job) / "work/raw_0000.png"
            while not frame.is_file():
                assert worker.poll() is None, read_job(job)
                if time.monotonic() - started > 140:
                    raise TimeoutError("Blender produced no real frame before fault injection")
                time.sleep(.1)
            worker.kill()
            worker.wait(timeout=10)
        finally:
            if worker.poll() is None:
                worker.kill()
    no_blender_for(job)
    state = get_render_job(job)
    assert state["status"] == "failed" and state["error"]["code"] == "interrupted", state
    assert frame.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == before
    result["owner_death"] = {"job": job, "error": state["error"]["code"], "frame_retained": True,
                             "duration_s": round(time.monotonic() - started, 3)}
    with (args.evidence / "restart.log").open("wb") as log, start("", log) as worker:
        assert worker.wait(timeout=30) == 0
    assert get_render_job(job) == state
    (args.evidence / "faults.json").write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
