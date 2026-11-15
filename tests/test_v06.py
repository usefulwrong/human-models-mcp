import base64
import hashlib
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from human_models_mcp import rendering


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    from human_models_mcp.registry import home

    root = home()
    for name in (
        "models",
        "scenarios",
        "models.lock.json",
        "requirements.lock",
        "docs",
        "benchmarks",
        "runtime-environment.json",
    ):
        (tmp_path / name).symlink_to(root / name)
    (tmp_path / "results").mkdir()
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    from human_models_mcp.core import run_scenario

    run = run_scenario("elbow_tracking", {"render": False})
    assert run["status"] == "computed"
    return run, tmp_path


def test_render_quality_and_command_boundaries():
    for bad in (
        {"width": 999},
        {"height": 1800},
        {"samples": 0},
        {"frames": 2000},
        {"device": "shell"},
        {"script": "malicious.py"},
        {"samples": True},
        {"width": 1920, "height": 1080, "samples": 128, "frames": 41},
    ):
        with pytest.raises(ValidationError):
            rendering.RenderOptions.model_validate(bad)
    assert set(rendering.list_render_profiles()["profiles"]) == {"preview", "scientific", "cinematic"}


def test_render_submission_snapshots_real_science_without_mutation(experiment):
    run, root = experiment
    before = {
        p.name: rendering.digest(p) for p in (root / "results" / run["run_id"]).iterdir() if p.is_file()
    }
    request = rendering.render_result(run["run_id"], idempotency_key="same")
    assert request["status"] == "queued"
    repeat = rendering.render_result(run["run_id"], idempotency_key="same")
    assert repeat["job_id"] == request["job_id"]
    assert (
        rendering.render_result(run["run_id"], options={"frames": 5}, idempotency_key="same")["status"]
        == "invalid_input"
    )
    folder = root / "render_jobs" / request["job_id"] / "input"
    assert folder.joinpath("trajectory.npz").is_file()
    assert rendering.digest(folder / "trajectory.npz") == run["artifacts"]["trajectory.npz"]["sha256"]
    assert before == {
        p.name: rendering.digest(p) for p in (root / "results" / run["run_id"]).iterdir() if p.is_file()
    }
    for layer in ("internal_organs", "muscle_volumes", "skin", "atlas_reference", "../../etc/passwd"):
        assert rendering.render_result(run["run_id"], layers=[layer])["status"] == "unsupported"
    assert rendering.render_result(run["run_id"], layers=["contact_forces"])["status"] == "unsupported"
    assert rendering.render_result("../../etc/passwd")["status"] == "invalid_input"


def test_render_source_corruption_is_rejected(experiment):
    run, root = experiment
    (root / "results" / run["run_id"] / "trajectory.npz").write_bytes(b"corrupt")
    result = rendering.render_result(run["run_id"])
    assert result["status"] == "invalid_input" and "checksum" in result["error"]["message"]
    assert not list((root / "render_jobs").glob("*/job.json"))


def test_static_experiment_does_not_pretend_to_offer_dynamic_frames(experiment):
    from human_models_mcp.core import run_scenario

    run = run_scenario("elbow_sweep", {"render": False})
    assert run["status"] == "computed"
    assert rendering.render_result(run["run_id"])["status"] == "unsupported"


def test_render_interrupt_status_and_chunk_security(experiment):
    run, root = experiment
    job = rendering.render_result(run["run_id"])
    folder = root / "render_jobs" / job["job_id"]
    job["status"] = "running"
    rendering.write_json(folder / "job.json", job)
    failed = rendering.get_render_job(job["job_id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "interrupted"
    original = (root / "results" / run["run_id"] / "manifest.json").read_bytes()
    data = bytes(range(256)) * 13000
    out = folder / "artifacts"
    out.mkdir()
    (out / "large.bin").write_bytes(data)
    failed.update(status="completed", artifacts={"large.bin": rendering.artifact_metadata(out / "large.bin")})
    rendering.write_json(folder / "job.json", failed)
    reconstructed = bytearray()
    offset = 0
    while offset < len(data):
        part = rendering.get_render_artifact(job["job_id"], "large.bin", offset)
        assert part["status"] == "ok"
        chunk = base64.b64decode(part["data"])
        assert len(chunk) <= rendering.MAX_CHUNK
        assert hashlib.sha256(chunk).hexdigest() == part["chunk_sha256"]
        reconstructed.extend(chunk)
        offset = part["next_offset"]
    assert bytes(reconstructed) == data
    for offset, length in ((-1, 10), (0, True), (0, rendering.MAX_CHUNK + 1), (len(data) + 1, 10)):
        assert (
            rendering.get_render_artifact(job["job_id"], "large.bin", offset, length)["status"]
            == "invalid_input"
        )
    assert rendering.get_render_artifact(job["job_id"], "../../etc/passwd")["status"] == "invalid_input"
    (out / "large.bin").write_bytes(data[:-1] + b"X")
    assert rendering.get_render_artifact(job["job_id"], "large.bin")["status"] == "integrity_error"
    assert (root / "results" / run["run_id"] / "manifest.json").read_bytes() == original


def test_object_npz_cannot_be_loaded(tmp_path):
    from human_models_mcp.scene_export import safe_archive

    path = tmp_path / "unsafe.npz"
    np.savez(path, states=np.array([{"do": "not execute"}], dtype=object))
    with pytest.raises(ValueError, match="object"):
        safe_archive(path)


def test_completion_during_stale_job_recovery_is_not_overwritten(experiment, monkeypatch):
    run, root = experiment
    record = rendering.render_result(run["run_id"])
    path = root / "render_jobs" / record["job_id"] / "job.json"
    record["status"] = "running"
    rendering.write_json(path, record)
    original = rendering.fcntl.flock

    def completed_before_lock(fd, operation):
        record["status"] = "completed"
        rendering.write_json(path, record)
        return original(fd, operation)

    monkeypatch.setattr(rendering.fcntl, "flock", completed_before_lock)
    assert rendering.get_render_job(record["job_id"])["status"] == "completed"


def test_new_tools_are_additive_and_import_is_lightweight():
    import subprocess
    import sys

    code = 'from human_models_mcp.server import list_render_profiles; import sys; list_render_profiles(); assert "bpy" not in sys.modules and "pxr" not in sys.modules and "mujoco" not in sys.modules'
    subprocess.run([sys.executable, "-c", code], check=True)
    from human_models_mcp.server import mcp
    import asyncio

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {
        "list_render_profiles",
        "render_result",
        "get_render_job",
        "get_render_artifact",
        "run_scenario",
        "get_artifact",
    } <= names
    assert len(names) == 14


def test_queue_symlink_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    (tmp_path / "outside").mkdir()
    (tmp_path / "render_jobs").symlink_to(tmp_path / "outside")
    assert rendering.get_render_job(str(uuid4()))["status"] == "invalid_input"
    assert not list((tmp_path / "outside").iterdir())


def test_offline_package_rejects_stale_image_source_and_locks():
    import importlib.util
    import json
    from human_models_mcp.registry import home

    root = home()
    spec = importlib.util.spec_from_file_location("package_check_v06", root / "scripts/package_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    record = json.loads((root / "runtime-environment.json").read_text())
    record.update(
        {
            n + "_sha256": hashlib.sha256((root / n).read_bytes()).hexdigest()
            for n in ("models.lock.json", "renderer.lock.json", "requirements-render.lock")
        }
    )
    assert module.image_matches_source(record)
    for key in (
        "source_sha256",
        "scenario_contracts",
        "requirements_lock_sha256",
        "models.lock.json_sha256",
        "renderer.lock.json_sha256",
        "requirements-render.lock_sha256",
    ):
        assert not module.image_matches_source({**record, key: None})
