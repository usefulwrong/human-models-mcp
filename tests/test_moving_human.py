"""Small self-contained fixture for typed replay identity and bounded artifacts."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

LAB = Path(__file__).resolve().parents[1] / "scripts/anatomy_lab"


FIXTURE = Path(__file__).with_name("fixtures") / "motion-view-synthetic.json"


def test_view_and_corrupted_local_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", [*sys.path, str(LAB)])
    from anatomy_lab import REQUEST
    from moving_transport import WholeMotion

    view = json.loads(FIXTURE.read_text())
    run_id = view["run_id"]
    run = tmp_path / "results" / run_id
    run.mkdir(parents=True)
    files = {"manifest.json": b"synthetic manifest", "trajectory.npz": b"synthetic trajectory",
             "motion.glb": b"synthetic transport bytes"}

    def digest(name):
        return hashlib.sha256(files[name]).hexdigest()

    for name, data in files.items():
        (run / name if name.endswith((".json", ".npz")) else tmp_path / name).write_bytes(data)
    atlas_hash = "2" * 64
    motion = {"schema_version": "hmm.anatomy.motion/1", "catalog_sha256": atlas_hash, "run_id": run_id,
              "trajectory_sha256": digest("trajectory.npz"), "source_manifest_sha256": digest("manifest.json"),
              "layers": {"MUSCLES": {"available": True}, "SKIN": {"available": False}},
              "frames": [{"state_index": 0}],
              "artifacts": {"motion.glb": {"sha256": digest("motion.glb"), "bytes": len(files["motion.glb"])}}}
    path = tmp_path / "motion.json"
    path.write_text(json.dumps(motion))
    scene_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    installed = WholeMotion(path, scene_sha, run.parent, atlas_hash)
    view["motion_sha256"] = scene_sha
    fields = {"operation": "whole.set_view", "run_id": run_id, "view": view}

    assert installed.call(REQUEST.validate_python(fields))["view"] == view
    with pytest.raises(ValueError, match="state is unavailable"):
        installed.call(REQUEST.validate_python({**fields, "view": {**view, "state_index": 1}}))
    with pytest.raises(ValueError, match="moving layers"):
        installed.call(REQUEST.validate_python({**fields, "view": {**view, "layers": ["SKIN"]}}))
    with pytest.raises(ValueError, match="catalog SHA"):
        WholeMotion(path, scene_sha, run.parent, "3" * 64).verified()
    with installed.open_artifact("motion.glb") as (stream, _):
        assert stream.read() == files["motion.glb"]
    (tmp_path / "motion.glb").write_bytes(b"x" * len(files["motion.glb"]))
    with pytest.raises(ValueError, match="artifact size or SHA"):
        with installed.open_artifact("motion.glb"):
            pytest.fail("corrupted motion GLB opened")
    (run / "trajectory.npz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="trajectory SHA"):
        installed.verified()
