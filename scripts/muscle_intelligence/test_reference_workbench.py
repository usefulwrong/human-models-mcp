"""The candidate evaluator and annotation chain can be exercised without atlas assets."""

import numpy as np
from pydantic import ValidationError
import pytest

from anatomy_lab import digest
from reference_workbench import AnnotationLog, compare
from registration_evidence import load_evidence


def test_geometric_holdout_and_transform():
    points = np.random.default_rng(7).uniform(-.1, .1, (70, 3))
    offset = np.array([0.012, -0.013, 0.004])
    result = compare(points, points + offset, points * 1000, np.eye(3), np.eye(4),
                     {"source_mm_to_native_geom_m": np.eye(4)}, [])
    assert result["sample_counts"]["held_out_icp_fit_source"] == len(points) - 2
    assert [x["name"] for x in result["markers"] if x["role"] == "HELD_OUT"] == ["y_min", "y_max"]
    for method in result["methods"].values():
        assert method["held_out_count"] == 2
        assert method["held_out_rms_mm"] < 1e-8
        assert method["rotation_det"] == pytest.approx(1)
        assert np.asarray(method["source_mm_to_target_geom_m"])[:3, 3] == pytest.approx(offset)
    assert result["manual_named_landmark_rigid"]["status"] == "NOT_RUN"


def test_annotation_review_rollback_and_evidence_pin(tmp_path):
    marker = {"id": "a", "name": "glenoid centre", "side": "left", "source_fj_id": "FJ1",
              "source_sha256": "a"*64, "target_geom": "scapula_mirror", "target_mesh_sha256": "b"*64,
              "source_frame": "BodyParts3D OBJ mm", "target_frame": "MuJoCo geom-local m", "role": "FIT",
              "source_mm": [1, 2, 3], "target_geom_m": [0.001, .002, .003], "source_evidence": "test"}
    decision = {"id": "obs1", "correspondence_id": "a", "reviewer": "test", "evidence": "test",
                "decision": "USE_FOR_COMPARISON"}
    undo = {**decision, "id": "obs2", "decision": "WITHDRAW", "supersedes": "obs1"}
    log = {"schema_version": "hmm.registration-annotations/1", "correspondences": [marker],
           "decisions": [decision, undo]}
    assert AnnotationLog.model_validate(log).decisions[-1].decision == "WITHDRAW"
    with pytest.raises(ValidationError, match="decision history"):
        AnnotationLog.model_validate({**log, "decisions": [undo, decision]})
    with pytest.raises(ValidationError, match="coordinate pair"):
        AnnotationLog.model_validate({**log, "correspondences": [{**marker, "source_mm": None}]})
    path = tmp_path / "receipt.json"
    raw = b'{"schema_version":"hmm.reference-registration/1","anatomical_registration":"NOT_VERIFIED"}'
    path.write_bytes(raw)
    assert load_evidence(str(path), digest(raw))["anatomical_registration"] == "NOT_VERIFIED"
    with pytest.raises(ValueError, match="SHA-256"):
        load_evidence(str(path), "0"*64)


def synthetic_landmarks():
    from landmark_geometry import surface

    vertices = np.asarray([[0, 0, 0], [100, 0, 0], [0, 80, 0], [0, 0, 50]])
    faces = [[0, 1, 2], [1, 2, 3], [0, 2, 3], [0, 1, 3]]
    mesh = {"source": surface(vertices, faces, 1), "target": surface(vertices / 1000, faces, 1000)}
    pair = {"source_fj_id": "FJ1", "source_bp_id": "BP1", "source_fma_id": "FMA1",
            "source_sha256": "a"*64, "target_mesh_sha256": "b"*64, "geometry_sha256": "c"*64,
            "anatomy_revision": "d"*64, "source_model_sha256": "e"*64, "target_geom": "synthetic",
            "side": "right", "source_frame": "BodyParts3D OBJ mm", "target_frame": "MuJoCo geom-local m"}
    names = tuple(f"synthetic point {i}" for i in range(4))
    items = [{
        **pair, "id": str(i), "name": name, "role": "FIT" if i < 3 else "HELD_OUT",
        "source_mm": vertices[i].tolist(), "target_geom_m": (vertices[i]/1000).tolist(),
        "source_evidence": "https://example.invalid/synthetic-fixture", "uncertainty_mm": 0.1,
        "method": "OPERATOR_SURFACE_PICK",
        **{field: {"face": 0 if i < 3 else 1, "weights": [int(j == min(i, 2)) for j in range(3)]}
           for field in ("source_anchor", "target_anchor")},
    } for i, name in enumerate(names)]
    decisions = [{"id": f"d{i}", "correspondence_id": str(i), "reviewer": "synthetic-fixture",
                  "evidence": "synthetic probe", "time": "2026-01-01T00:00:00Z",
                  "decision": "USE_FOR_COMPARISON"} for i in range(4)]
    return {"schema_version": "hmm.registration-annotations/2", "correspondences": items,
            "decisions": decisions}, pair, mesh, names


@pytest.mark.parametrize(("field", "value"), [
    ("side", "left"), ("source_fma_id", "FMA2"), ("source_bp_id", "BP2"),
    ("source_sha256", "f"*64), ("target_mesh_sha256", "f"*64), ("anatomy_revision", "f"*64),
    ("geometry_sha256", "f"*64), ("target_frame", "MuJoCo world m"),
    ("target_geom_m", [100, 0, 0]), ("source_mm", [0.1, 0, 0]),
    ("source_evidence", "unknown"), ("source_mm", [float("nan"), 0, 0]),
    ("source_anchor", {"face": 300, "weights": [0, 1, 0]}),
])
def test_synthetic_annotation_negatives(field, value):
    from reference_workbench import pinned_annotations

    doc, pair, mesh, names = synthetic_landmarks()
    doc["correspondences"][1][field] = value
    with pytest.raises(ValueError):
        pinned_annotations(AnnotationLog.model_validate(doc), pair, mesh, names)


def test_synthetic_duplication_rollback_and_holdout():
    from reference_workbench import Correspondence, pinned_annotations

    doc, pair, mesh, names = synthetic_landmarks()
    verified = pinned_annotations(AnnotationLog.model_validate(doc), pair, mesh, names)
    assert {p["status"] for p in verified} == {"OPERATOR_CANDIDATE"}
    doc["correspondences"][-1].update({k: doc["correspondences"][0][k] for k in
                                     ("source_mm", "target_geom_m", "source_anchor", "target_anchor")})
    with pytest.raises(ValueError, match="leakage"):
        pinned_annotations(AnnotationLog.model_validate(doc), pair, mesh, names)
    doc["decisions"].append({**doc["decisions"][-1], "id": "undo", "supersedes": "d3", "decision": "WITHDRAW"})
    assert len(pinned_annotations(AnnotationLog.model_validate(doc), pair, mesh, names)) == 3
    base, _, _, _ = synthetic_landmarks()
    selected = [Correspondence.model_validate(c) for c in base["correspondences"]]
    cloud = np.random.default_rng(17).uniform(-.1, .1, (80, 3))
    def fit(points):
        return compare(cloud, cloud, cloud * 1000, np.eye(3), np.eye(4),
                       {"source_mm_to_native_geom_m": np.eye(4)}, points)["manual_named_landmark_rigid"]
    initial = fit(selected)
    perturbed = fit([*selected[:-1], selected[-1].model_copy(update={"target_geom_m": (0, 0, .051)})])
    assert initial["status"] == "CANDIDATE"
    assert perturbed["source_mm_to_target_geom_m"] == initial["source_mm_to_target_geom_m"]
    assert initial["held_out_max_mm"] == pytest.approx(0)
    assert perturbed["held_out_max_mm"] == pytest.approx(1)


def test_synthetic_mirror_scale_degenerate_and_absent_dataset(tmp_path):
    from landmark_geometry import obj, surface, validate_transform
    from reference_workbench import pinned_annotations

    good = np.diag([.001, .001, .001, 1])
    validate_transform(good)
    for bad in (np.diag([-.001, .001, .001, 1]), np.diag([1, 1, 1, 1])):
        with pytest.raises(ValueError, match="scale or reflection"):
            validate_transform(bad)
    with pytest.raises(ValueError, match="degenerate"):
        surface([[0, 0, 0], [50, 0, 0], [100, 0, 0]], [[0, 1, 2]], 1)
    with pytest.raises(FileNotFoundError):
        obj(tmp_path / "missing.obj")
    doc, pair, mesh, names = synthetic_landmarks()
    mesh["source"]["triangles"][0] = [0, 0, 0]
    with pytest.raises(ValueError, match="degenerate triangle"):
        pinned_annotations(AnnotationLog.model_validate(doc), pair, mesh, names)


def test_synthetic_receipt_v2_independent_statuses(tmp_path):
    import json

    from registration_evidence import at_frame

    pins = {"run_id": "synthetic", **{k: "a"*64 for k in (
        "motion_sha256", "mapping_revision_sha256", "source_result_sha256", "source_model_sha256",
        "anatomy_revision")}}
    doc = dict(pins, schema_version="hmm.reference-registration/2", anatomical_registration="NOT_VERIFIED",
               frames=[{"state_index": 0}], pilots={}, claims={"source_provenance": "PINNED",
               "geometry_fit": "CANDIDATE", "expert_review": "PENDING", "attachment_footprint": "NOT_VERIFIED",
               "human_physiology": "NOT_VALIDATED"}, independent_landmarks={"count": 0})
    def publish(data):
        raw = json.dumps(data).encode()
        path = tmp_path / "receipt.json"
        path.write_bytes(raw)
        return load_evidence(str(path), digest(raw))
    receipt = publish(doc)
    with pytest.raises(ValueError, match="different source"):
        at_frame(receipt, "", {**pins, "source_result_sha256": "b"*64}, doc["frames"][0], [], None)
    with pytest.raises(ValueError, match="different saved state"):
        at_frame(receipt, "", pins, {"state_index": 0, "frame_time": 11}, [], None)
    with pytest.raises(ValueError, match="unsupported"):
        publish({**doc, "anatomical_registration": "VERIFIED"})
