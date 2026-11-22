import json
from uuid import uuid4

import numpy as np
import pytest

from human_models_mcp.atlas import atlas_inputs, atlas_lock, provision_atlas, verify_asset
from human_models_mcp.atlas_registration import register, rigid_fit
from human_models_mcp.evidence import get_evidence
from human_models_mcp.reference_motion import FIT3D_INDICES, compare_motion, import_fit3d, write_comparison


def test_atlas_license_hash_size_and_landmark_rejections(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="explicit acceptance"):
        provision_atlas("MIT")
    with pytest.raises(ValueError, match="offline atlas cache miss"):
        provision_atlas(atlas_lock()["license"], offline=True)
    with pytest.raises(ValueError, match="license receipt"):
        atlas_inputs()
    obj = tmp_path / "FJ1447.obj"
    asset = atlas_lock()["files"][obj.name]
    obj.write_bytes(b"a")
    with pytest.raises(ValueError, match="wrong-size"):
        verify_asset(obj, asset)
    obj.write_bytes(b"a" * asset["bytes"])
    with pytest.raises(ValueError, match="checksum"):
        verify_asset(obj, asset)
    with pytest.raises(ValueError, match="pin mismatch"):
        register(None, None, {"revision": "wrong", "asset_sha256": "wrong"}, tmp_path)
    points = np.eye(3)
    r, t = rigid_fit(points, points + 2)
    np.testing.assert_allclose(points @ r + t, points + 2)
    assert np.linalg.det(r) > .999999
    with pytest.raises(ValueError, match="degenerate"):
        rigid_fit(np.zeros((3, 3)), points)
    with pytest.raises(ValueError, match="invalid"):
        rigid_fit(np.full((3, 3), np.nan), points)


def test_evidence_does_not_promote_failed_numeric_or_unsupported_claim(monkeypatch):
    run = {
        "run_id": "example", "status": "computed", "engine": {"name": "mujoco"}, "model": {},
        "scenario_id": "pushup", "scenario_version": "1", "scenario_sha256": "sample",
        "execution": {"simulation_time_s": 2.4, "controller": None, "parameters": {"control": "assisted_muscle"},
                      "environment": {"package_version": "0.8.0"}},
        "scientific": {"limits": [], "limitations": ["Assisted"], "citations": [],
                       "checks": [{"name": "finite_state", "status": "pass"}],
                       "acceptance": {"numerical_bounds": "FAIL"}},
        "outputs": {"metrics": [{"name": "example", "value": 1, "unit": "N"}]},
    }
    monkeypatch.setattr("human_models_mcp.evidence.get_run", lambda _: run)
    result = get_evidence("example", "metric:example")
    assert result["claims"][0]["evidence_class"] == "computed_only"
    assert result["control_mode"] == "assisted_muscle"
    assert get_evidence("example", "computed_muscle_strain")["status"] == "unsupported"


def test_fit3d_contract_with_synthetic_frames_only(tmp_path, monkeypatch):
    """Synthetic control of the import and comparison maths, with no external evidence."""
    home = tmp_path / "project"
    home.mkdir()
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(home))
    path = tmp_path / "synthetic.json"
    base = np.array([
        [.0, 0, .32], [0, -.13, .32], [-.43, -.13, .22], [-.84, -.13, .09],
        [0, .13, .32], [-.43, .13, .22], [-.84, .13, .09],
        [.48, .20, .68], [.48, .20, .38], [.48, .20, .10],
        [.48, -.20, .68], [.48, -.20, .38], [.48, -.20, .10],
    ])
    xyz = np.tile(base, (21, 1, 1))
    for frame in range(len(xyz)):
        n = np.sin(np.pi * frame / 20)
        xyz[frame, [7, 10], 2] -= .18 * n
        xyz[frame, [8, 11], 0] -= .17 * n
        xyz[frame, [8, 11], 2] -= .055 * n
    raw = np.zeros((len(xyz), 25, 3))
    raw[:, FIT3D_INDICES] = xyz
    path.write_text(json.dumps({"joints3d_25": raw.tolist()}))
    meta = {"version": "synthetic control", "subject": "fixture", "motion": "pushup", "phase_frames": [0, 10, 20],
            "world_to_zup": np.eye(3, dtype=int).tolist(), "floor_z_m": 0.0,
            "coordinate_system": "fixture Z up", "unit": "m", "camera": "world"}
    reference = import_fit3d(path, meta, True)
    result, aligned = compare_motion(reference, xyz, np.asarray(reference["time_s"]), [0, 10, 20])
    np.testing.assert_allclose(aligned, xyz, atol=1e-15, rtol=0)
    assert result["metrics"]["mpjpe_m"] < 1e-15
    assert result["time_alignment"]["bottom_phase_difference"] == 0
    for bad_clock in ([], [*reference["time_s"][:-1], np.inf]):
        with pytest.raises(ValueError, match="clocks"):
            compare_motion(dict(reference, time_s=bad_clock), xyz, reference["time_s"], [0, 10, 20])
    assert write_comparison("run", None, None, None)["reason"] == "LICENSED_DATA_NOT_PROVIDED"
    with pytest.raises(ValueError, match="license"):
        import_fit3d(path, meta, False)
    with pytest.raises(ValueError, match="permutation"):
        import_fit3d(path, dict(meta, unit="mm"), True)
    with pytest.raises(ValueError, match="permutation"):
        import_fit3d(path, dict(meta, world_to_zup=[[1, 0, 0], [0, -1, 0], [0, 0, 1]]), True)
    with pytest.raises(ValueError, match="phase"):
        import_fit3d(path, dict(meta, phase_frames=[0, 20, 10]), True)
    raw[10, 11] = np.nan
    path.write_text(json.dumps({"joints3d_25": raw.tolist()}))
    with pytest.raises(ValueError, match="nonfinite"):
        import_fit3d(path, meta, True)


def test_recipe_cache_rejects_a_different_renderer_lock(tmp_path, monkeypatch):
    from human_models_mcp.rendering import digest, render_result
    from human_models_mcp.render_worker import process_job

    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    run_id = str(uuid4())
    run = tmp_path / "results" / run_id
    run.mkdir(parents=True)
    (run / "series.csv").write_text("time_s\n0\n0.1\n0.2\n")
    np.savez(run / "trajectory.npz", time_s=[0, .1, .2])
    manifest = run / "manifest.json"
    manifest.write_text(json.dumps({
        "run_id": run_id, "status": "computed", "scenario_id": "pushup",
        "execution": {"integration_steps": 3}, "scientific": {"limitations": []},
        "artifacts": {p.name: {"sha256": digest(p)} for p in run.iterdir()},
    }))
    original = manifest.read_bytes()
    lock = tmp_path / "renderer.lock.json"
    lock.write_text('{"renderer": "first"}')

    def submit():
        return render_result(run_id, recipe="pushup_muscle_paths", options={"frames": 3})

    first = submit()
    assert first["status"] == "queued", first
    assert submit()["job_id"] == first["job_id"]
    lock.write_text('{"renderer": "second"}')
    after = submit()
    assert after["status"] == "queued" and after["job_id"] != first["job_id"]
    failed = process_job(first["job_id"])
    assert failed["error"]["code"] == "integrity_error"
    assert manifest.read_bytes() == original
