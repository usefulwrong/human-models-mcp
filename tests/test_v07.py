import json

import numpy as np
import pytest
from pydantic import ValidationError

from human_models_mcp.adapters.pushup import (
    PADS, anatomical_group, pushup_model, recruit, reference_poses, simulate_pushup, target_pose, transmission,
)
from human_models_mcp.registry import PushupParameters, discover


def test_pushup_manifest_and_boundary():
    scenario = next(s for s in discover()["scenarios"] if s["id"] == "pushup")
    assert scenario["model"] == "ms_human_700" and scenario["defaults"]["control"] == "muscle"
    for params in ({"control": "shell"}, {"friction": 0.0}, {"muscle_strength_scale": 2.0},
                   {"timestep_s": .1}, {"render": True}, {"path": "model.xml"}):
        with pytest.raises(ValidationError):
            PushupParameters.model_validate(params)
    assert anatomical_group("PECM2_r") == "pectoralis_major"
    assert anatomical_group("unknown") == "unmapped_source_identifier"


def test_reference_is_bilateral_supported_and_within_source_equalities():
    mj, model, data = pushup_model(friction=1.3)
    reference, metadata = reference_poses(mj, model, data)
    assert metadata["max_residual"] < 1e-4
    assert np.array_equal(target_pose(reference, 0), target_pose(reference, 2.4))
    for qpos in reference:
        data.qpos[:] = qpos
        mj.mj_forward(model, data)
        assert np.max(abs(data.efc_pos[:model.neq])) < 1e-10
        assert np.max(abs(data.geom_xpos[[model.geom(n).id for n in PADS]][:, 2] - [.025, .025, .015, .015])) < 2e-6
    active = np.array([i for i in range(6, model.njnt) if i not in model.eq_obj1id])
    original = data.act.copy()
    recruit(mj, model, data, active, np.zeros(len(active)))
    assert np.array_equal(original, data.act) and np.all((data.ctrl >= 0) & (data.ctrl <= 1))


def test_real_muscle_cycle_and_sparse_force_accounting(tmp_path):
    scenario = next(s for s in discover()["scenarios"] if s["id"] == "pushup")
    result = simulate_pushup(scenario["defaults"], tmp_path, scenario["validation"])
    assert result["acceptance"]["full_pushup"] == result["acceptance"]["muscle_driven"] == "PASS"
    mj, model, data = pushup_model(friction=1.3)
    saved = np.load(tmp_path / "trajectory.npz")
    for index in (0, 60, 120):
        mj.mj_setState(model, data, saved["states"][index], int(saved["state_spec"]))
        mj.mj_forward(model, data)
        assert not np.any(data.qfrc_applied) and not np.any(data.xfrc_applied)
        chunk = np.load(tmp_path / f"muscles_{index // 20:03d}.npz")
        offset = index % 20
        assert np.array_equal(data.act, chunk["activation"][offset])
        assert np.allclose(data.actuator_force, chunk["force_N"][offset], rtol=0, atol=1e-10)
        assert np.allclose(transmission(model, data).T @ data.actuator_force, data.qfrc_actuator, rtol=0, atol=1e-8)
    assert len(json.loads((tmp_path / "actuators.json").read_text())["actuators"]) == 700
    assert max(p.stat().st_size for p in tmp_path.iterdir()) < 2 * 1024 * 1024


def test_fresh_mcp_client_exports_pushup_data(tmp_path):
    import os
    import subprocess
    import sys
    from human_models_mcp.registry import home

    root = home()
    for name in ("models", "scenarios", "models.lock.json", "requirements.lock", "docs", "runtime-environment.json"):
        (tmp_path / name).symlink_to(root / name)
    result = subprocess.run([sys.executable, str(root / "examples/mcp-client/client.py"),
        "--scenario", "pushup", "--save-dir", str(tmp_path / "export"), "--output", str(tmp_path / "client.json")],
        env={**os.environ, "HUMAN_MODELS_HOME": str(tmp_path)}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr + result.stdout
    evidence = json.loads((tmp_path / "client.json").read_text())
    assert evidence["run"]["scientific"]["acceptance"]["muscle_driven"] == "PASS"
    assert (tmp_path / "export/index.html").is_file()
    assert len(list((tmp_path / "export").glob("muscles_*.npz"))) == 7
