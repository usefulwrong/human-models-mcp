"""Metadata/failure tests; toy XML here is never evidence of human biomechanics."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from human_models_mcp import core
from human_models_mcp.registry import home
from human_models_mcp.results import get_run


def local_home(tmp_path, monkeypatch):
    original = home()
    for name in ("models", "models.lock.json", "scenarios", "requirements.lock"):
        (tmp_path / name).symlink_to(original / name)
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))


def test_all_native_joint_types():
    import mujoco
    from human_models_mcp.adapters.mujoco import joint_record
    xml = '<mujoco><worldbody>' + ''.join(
        f'<body><joint name="{kind}" type="{kind}"/><geom type="sphere" size=".1"/></body>'
        for kind in ("free", "ball", "slide", "hinge")) + '</worldbody></mujoco>'
    model = mujoco.MjModel.from_xml_string(xml)
    records = [joint_record(model, i) for i in range(model.njnt)]
    assert [r["type"] for r in records] == ["free", "ball", "slide", "hinge"]
    assert [r["qpos_width"] for r in records] == [7, 4, 1, 1]
    assert [r["dof_width"] for r in records] == [6, 3, 1, 1]
    assert records[0]["range"] is None and records[1]["unit"] == "unit_quaternion"


def test_joint_source_search():
    from human_models_mcp.sources import search_sources
    result = search_sources("knee_angle_r", limit=10)
    match = next(row for row in result["matches"] if row["id"] == "knee_angle_r")
    assert match["evidence_type"] == "upstream_joint_identifier"
    assert len(match["source_sha256"]) == 64 and match["license"] == "Apache-2.0"


def test_requested_render_failure_is_not_success(tmp_path, monkeypatch):
    local_home(tmp_path, monkeypatch)
    def failed_render(request):
        return {"status": "computed", "metrics": [], "checks": [], "counts": {}, "timestep_s": .002,
                "render": {"status": "failed", "render_backend": "none", "message": "injected renderer failure"}}
    monkeypatch.setattr(core, "worker", failed_render)
    run = core.run_scenario("elbow_sweep")
    assert run["status"] == "failed" and run["error"]["code"] == "render_failed"
    assert run["execution"]["numeric_status"] == "computed"
    assert get_run(run["run_id"]) == run


def test_real_disabled_renderer_retains_numeric_failure(tmp_path, monkeypatch):
    local_home(tmp_path, monkeypatch)
    monkeypatch.setenv("MUJOCO_GL", "disable")
    run = core.run_scenario("elbow_sweep")
    assert run["status"] == "failed" and run["error"]["code"] == "render_failed"
    assert run["execution"]["numeric_status"] == "computed"
    assert run["outputs"]["metrics"][0]["unit"] == "m"
    assert "series.csv" in run["artifacts"] and run["render"]["status"] == "failed"


def test_stale_running_record_recovers_and_retains_partial_data(tmp_path, monkeypatch):
    local_home(tmp_path, monkeypatch)
    run_id = "6033a14d-7cd0-41f7-a7f5-e132f22d5ea7"
    folder = tmp_path / "results" / run_id
    folder.mkdir(parents=True)
    (folder / "partial.csv").write_text("preserved")
    (folder / "manifest.json").write_text(json.dumps({"run_id": run_id, "status": "running"}))
    with core.executor_lock():
        assert get_run(run_id)["status"] == "running"
    recovered = get_run(run_id)
    assert recovered["status"] == "failed" and recovered["error"]["code"] == "interrupted"
    assert recovered["scientific"]["validation_level"] == "unvalidated"
    assert (folder / "partial.csv").read_text() == "preserved"


@pytest.mark.parametrize("victim", ["worker", "executor"])
def test_real_process_kill_does_not_leave_success(tmp_path, monkeypatch, victim):
    local_home(tmp_path, monkeypatch)
    process = subprocess.Popen([sys.executable, "-c",
        "from human_models_mcp.core import run_scenario;run_scenario('elbow_sweep', {'samples':101})"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
    worker = None
    try:
        for _ in range(500):
            children = Path(f"/proc/{process.pid}/task/{process.pid}/children")
            try:
                ids = children.read_text().split()
            except FileNotFoundError:
                ids = []
            native = []
            for pid in ids:
                try:
                    command = Path(f"/proc/{pid}/cmdline").read_bytes()
                except FileNotFoundError:
                    continue
                if b"human_models_mcp.worker" in command:
                    native.append(int(pid))
            if native:
                worker = native[0]
                break
            time.sleep(.01)
        assert worker is not None, "native worker was not observed"
        if victim == "worker":
            os.kill(worker, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=10)
        for _ in range(300):
            stat = Path(f"/proc/{worker}/stat")
            try:
                state = stat.read_text().split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(.01)
        else:
            pytest.fail("worker continued running after executor death")
        manifests = list((tmp_path / "results").glob("*/manifest.json"))
        assert len(manifests) == 1
        run = get_run(manifests[0].parent.name)
        assert run["status"] == "failed" and run["scientific"]["validation_level"] == "unvalidated"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
