"""Platform-neutral locking and Windows Job Object contract checks."""

from contextlib import contextmanager
import os
import subprocess
import sys
import time

import pytest

from human_models_mcp.runtime.locking import file_lock


def test_lock_contends_across_processes_and_recovers_after_owner_death(tmp_path):
    lock = tmp_path / "scientific queue.lock"
    child = """
import time, sys
from pathlib import Path
from human_models_mcp.runtime.locking import file_lock
with file_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    time.sleep(30)
"""
    with subprocess.Popen([sys.executable, "-c", child, str(lock)], stdout=subprocess.PIPE,
                          encoding="utf-8") as owner:
        try:
            assert owner.stdout.readline().strip() == "locked"
            with file_lock(lock, blocking=False) as acquired:
                assert not acquired
        finally:
            owner.kill()
            owner.wait(timeout=10)
    with file_lock(lock, blocking=False) as acquired:
        assert acquired


def test_science_recovery_reloads_after_obtaining_lock(tmp_path, monkeypatch):
    import json
    from human_models_mcp import results

    run = "6033a14d-7cd0-41f7-a7f5-e132f22d5ea7"
    folder = tmp_path / run
    folder.mkdir()
    current = folder / "manifest.json"
    current.write_text('{"status":"running"}', encoding="utf-8")
    monkeypatch.setattr(results, "store", lambda: tmp_path)

    @contextmanager
    def finished_before_lock(*args, **kwargs):
        current.write_text('{"status":"computed"}', encoding="utf-8")
        yield True

    monkeypatch.setattr(results, "file_lock", finished_before_lock)
    assert results.get_run(run) == {"status": "computed"}
    assert json.loads(current.read_bytes()) == {"status": "computed"}


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object fault injection")
@pytest.mark.parametrize("mode", ["timeout", "owner-death"])
def test_windows_job_terminates_descendant_tree(tmp_path, mode):
    import ctypes
    from ctypes import wintypes

    from human_models_mcp.runtime.processes import managed_process

    pidfile = tmp_path / "descendant.txt"
    child = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    grandparent = """
import subprocess,sys
from human_models_mcp.runtime.processes import managed_process
with managed_process([sys.executable, "-c", sys.argv[1], sys.argv[2]], memory=128*1024**2,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as job:
    job.wait()
"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    def descendant():
        for _ in range(250):
            try:
                pid = int(pidfile.read_text())
            except (FileNotFoundError, ValueError):
                time.sleep(.05)
            else:
                handle = kernel.OpenProcess(0x00100001, False, pid)
                if handle:
                    return handle
        pytest.fail("bounded workload never started")

    handle = None
    try:
        if mode == "timeout":
            with pytest.raises(subprocess.TimeoutExpired):
                with managed_process([sys.executable, "-c", child, str(pidfile)], memory=128*1024**2,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL) as process:
                    handle = descendant()
                    process.wait(timeout=.1)
        else:
            with subprocess.Popen([sys.executable, "-c", grandparent, child, str(pidfile)]) as owner:
                try:
                    handle = descendant()
                finally:
                    owner.kill()
                    owner.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 10_000) == 0, "orphaned descendant"
    finally:
        if handle:
            if kernel.WaitForSingleObject(handle, 0):
                kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="junction test needs Windows NTFS")
def test_result_junction_is_rejected(tmp_path, monkeypatch):
    from human_models_mcp import results

    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "results"
    subprocess.run(["cmd", "/d", "/c", "mklink", "/j", str(junction), str(outside)], check=True)
    try:
        with pytest.raises(ValueError, match="reparse point"):
            results.store()
    finally:
        junction.rmdir()


def test_portable_model_vfs_matches_loaded_model():
    import mujoco as mj
    import numpy as np

    from human_models_mcp.adapters.mujoco import load, model_assets
    from human_models_mcp.catalog import MODEL_FILES

    for model_id, filename in MODEL_FILES.items():
        _, direct, state = load(model_id=model_id)
        with mj.MjVfs() as vfs:
            for name, data in model_assets(filename).items():
                vfs[name] = data
            spec = mj.MjSpec.from_file(filename, vfs=vfs)
            virtual = spec.compile(vfs=vfs)
        assert (virtual.nq, virtual.nv, virtual.nu) == (direct.nq, direct.nv, direct.nu)
        np.testing.assert_array_equal(virtual.mesh_vert, direct.mesh_vert)
        replay = mj.MjData(virtual)
        mj.mj_resetDataKeyframe(virtual, replay, 0)
        mj.mj_forward(virtual, replay)
        np.testing.assert_array_equal(replay.qpos, state.qpos)
        np.testing.assert_array_equal(replay.actuator_length, state.actuator_length)


def test_mcp_configuration_round_trips_windows_paths():
    import json
    from pathlib import Path, PureWindowsPath
    import tomllib

    script = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(script))
    try:
        from print_client_config import configuration
    finally:
        sys.path.remove(str(script))

    root = PureWindowsPath("D:/Research Projects/Human Models MCP")
    python = str(root / ".runtime/python/python.exe")
    native = tomllib.loads(configuration("native", "toml", root=root, python=python))
    anatomy = json.loads(configuration("anatomy", "json", root=root, python=python))
    assert native["mcp_servers"]["human_models"]["command"] == python
    assert native["mcp_servers"]["human_models"]["env"]["HUMAN_MODELS_HOME"] == str(root)
    assert anatomy["mcpServers"]["anatomy_lab"]["args"][-2] == str(root / "scripts/native.py")


@pytest.mark.skipif(os.name != "nt", reason="Windows scientific owner interruption")
def test_windows_scientific_busy_and_interrupted_recovery(tmp_path, monkeypatch):
    import json
    import shutil

    from human_models_mcp.registry import home
    from human_models_mcp.results import get_run

    checkout = home()
    for name in ("models", "scenarios"):
        shutil.copytree(checkout / name, tmp_path / name)
    for name in ("models.lock.json", "requirements-windows-x64.lock"):
        shutil.copyfile(checkout / name, tmp_path / name)
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    execute = "import json,sys; from human_models_mcp.core import run_scenario; print(json.dumps(run_scenario(sys.argv[1])))"
    with subprocess.Popen([sys.executable, "-c", execute, "pushup_flat_palm"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as owner:
        try:
            for _ in range(400):
                manifests = list((tmp_path / "results").glob("*/manifest.json"))
                if manifests and get_run(manifests[0].parent.name)["status"] == "running":
                    break
                assert owner.poll() is None
                time.sleep(.025)
            else:
                pytest.fail("scientific owner never started a bounded run")
            attempt = subprocess.check_output([sys.executable, "-c", execute, "elbow_sweep"],
                                              encoding="utf-8", timeout=15)
            assert json.loads(attempt)["status"] == "busy"
        finally:
            owner.kill()
            owner.wait(timeout=10)
    record = get_run(manifests[0].parent.name)
    assert record["status"] == "failed" and record["error"]["code"] == "interrupted"
    assert record["scientific"]["validation_level"] == "unvalidated"
