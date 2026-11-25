"""Focused regressions for exact identities, bounded reads, and the real pinned installation."""

from io import BytesIO
import json
import os
import re
from uuid import UUID
from zipfile import ZipFile

import numpy as np
from pydantic import ValidationError
import pytest

from anatomy_lab import REQUEST
from crosswalk import bodyparts_asset, candidates, canonical_path, display_asset, source_side, unique
from muscle_data import MuscleData, arrays, derived, verified_bytes
from lab_mcp import registry

RUN = "14f5e412-a31e-4b72-b008-278bd8c96ce3"


def npz(**kwargs):
    stream = BytesIO()
    np.savez_compressed(stream, **kwargs)
    return stream.getvalue()


def test_names_are_token_bounded_and_sided():
    right = {"fma_id": 111}
    idx = {("right", "adductor longus"): [right]}
    aliases = {"addlong": "adductor longus"}
    assert source_side("PECM1_r") == "right" and source_side("PECM1_l") == "left"
    assert candidates("addlong_r", "right", aliases, idx) == [right]
    assert candidates("addlong_r", "left", aliases, idx) == []
    assert candidates("fake_addlong_r", "right", aliases, idx) == []
    assert candidates("addlonger_r", "right", aliases, idx) == []
    with pytest.raises(ValueError, match="duplicate fj_id"):
        unique([{"fj_id": "FJ11"}, {"fj_id": "FJ11"}], "fj_id")


def test_source_disagreement_is_explicit():
    c = {"fma_id": 1, "side": "right"}
    m = {"fj_id": "FJ11", "identity_status": "MATCH", "pinned_filename_fma_id": 2,
         "side": "left", "bp_id": "BP11", "label": "left muscle", "sha256": "0"*64}
    result = bodyparts_asset(c, m, {"revision": "test", "url": "fixture"}, {})
    assert result["source_membership"] == "conflicting"
    with pytest.raises(ValueError, match="identity conflict"):
        display_asset({"source_node": 0, "name": "left muscle", "fma_id": "FMA2", "crosswalk": "MATCH"},
                      {"nodes": [{"name": "left muscle"}]}, b"", {}, {}, {**c, "label": "right muscle"},
                      result)


def test_corrupted_archive_and_hash_fail_closed(tmp_path):
    for wrong in (b"broken", npz(array=np.array([float("inf")])), npz(array=np.array([object()]))):
        with pytest.raises(ValueError):
            arrays(wrong, ("array",))
    raw = BytesIO()
    with ZipFile(raw, "w") as archive:
        archive.writestr("../array.npy", b"")
    with pytest.raises(ValueError, match="unexpected"):
        arrays(raw.getvalue(), ("array",))
    raw = BytesIO()
    with pytest.warns(UserWarning), ZipFile(raw, "w") as archive:
        archive.writestr("array.npy", b"")
        archive.writestr("array.npy", b"")
    with pytest.raises(ValueError, match="duplicate"):
        arrays(raw.getvalue(), ("array",))
    with pytest.raises(ValueError, match="oversized"):
        arrays(npz(array=np.zeros(9 << 20, dtype=np.uint8)), ("array",))
    (tmp_path / "s.npz").write_bytes(b"broken")
    with pytest.raises(ValueError, match="SHA-256"):
        verified_bytes(tmp_path, {"artifacts": {"s.npz": {"sha256": "0"*64, "bytes": 6}}}, "s.npz", 20)
    (tmp_path / "link.npz").symlink_to(tmp_path / "s.npz")
    with pytest.raises(ValueError, match="invalid local asset"):
        verified_bytes(tmp_path, {}, "link.npz", 20)


def test_derived_metrics_preserve_sign_and_scope():
    data = np.array([[-4, 3], [-1, 6]])
    assert derived("force_N", data)[1].tolist() == [-1, 5]
    assert derived("force_magnitude_N", abs(data))[1].tolist() == [7, 7]
    assert derived("activation", data)[1].tolist() == [-.5, 2.5]
    assert derived("length_m", data) == (None, None)
    assert derived("work_J", data)[1].tolist() == [-1, 5]
    for fields in ({"actuator_ids": list(range(700))}, {"actuator_ids": [-1]}, {"actuator_ids": [700]},
                   {"actuator_ids": [0,0]}, {"actuator_ids": [0], "script": "some text"},
                   {"group_id": "../right"}, {"actuator_ids": [0], "start_s": float("inf")}):
        with pytest.raises(ValidationError):
            REQUEST.validate_python({"operation": "muscle.timeseries", "run_id": RUN, **fields})


def test_canonical_path_keeps_digits_and_source_levels():
    empty_table = {"labels": {}}
    def parse(name, files):
        return canonical_path({"exact_name": name, "side": source_side(name), "source_actuator_files": files},
                              empty_table, {})
    assert parse("FDPR_r", ["assets/muscle/Muscle_Arm_r.xml"])["digit"] == 4
    assert parse("QL_ant_I_2-T12_l", ["assets/muscle/Muscle_Torso.xml"])["vertebral_or_rib_tokens"] == ["T12"]
    assert parse("EO_R5_l", ["assets/muscle/Muscle_Torso.xml"])["stem"] == "EO_R5"


@pytest.mark.skipif(not os.environ.get("HMM_LAB_MUSCLE_CROSSWALK"), reason="real installation required")
def test_pinned_inventory_and_chunk_negatives(tmp_path):
    installed = registry()
    analytics = installed.whole.muscles
    context = analytics.context(UUID(RUN))
    scene, mapping, root, manifest, base = context
    assert len(mapping["rows"]) == 700 and len({r["exact_name"] for r in mapping["rows"]}) == 700
    assert all(r["links"] and r["source_tendon_files"] for r in mapping["rows"])
    for side in ("right", "left"):
        for group, names in [
            ("pectoralis_major", ("PECM1", "PECM2", "PECM3")),
            ("triceps_brachii", ("TRIlong", "TRIlat", "TRImed")),
        ]:
            ids = mapping["groups"][f"{group}:{side}"]["actuator_ids"]
            assert [mapping["rows"][i]["exact_name"] for i in ids] == [n+"_"+side[0] for n in names]
            assert all(mapping["rows"][i]["side"] == side for i in ids)
    assert mapping["counts"]["accepted_anatomical_mappings"] >= 10
    if mapping.get("coverage_revision") == 2:
        assert mapping["counts"]["unique_accepted_fma_parts"] == 74
        assert len(mapping["motion_display_assets"]) == 290
        assert all(len(row["route_evidence"]["observed_dL_dq"]) == 3 for row in mapping["rows"])
    assert base["acceptance"]["muscle_driven"] == "NOT_ACHIEVED"
    with pytest.raises(ValueError, match="invalid local asset"):
        MuscleData(analytics.whole, tmp_path / "missing-crosswalk.json", analytics.sha).context(UUID(RUN))
    with pytest.raises(ValueError, match="crosswalk SHA"):
        analytics.mapping(b"{}")
    with pytest.raises(ValueError, match="anatomy, motion"):
        analytics.context(UUID(RUN), {**scene, "catalog_sha256": "0"*64})
    # Copy verified metadata, mutate only a scratch chunk. The pinned source remains read-only.
    for name in ("trajectory.npz", "trajectory_metadata.json", "actuators.json"):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    local = (scene, mapping, tmp_path, manifest, base)
    with pytest.raises(ValueError, match="invalid local asset: muscles_000.npz"):
        analytics.series(local, "activation", [0])
    (tmp_path / "muscles_000.npz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="artifact SHA-256"):
        analytics.series(local, "activation", [0])
    assert {"1", "N", "m", "m/s", "W"}.issubset(set(json.loads((root/"trajectory_metadata.json").read_bytes())["units"].values()))
    assert re.fullmatch("[0-9a-f]{64}", base["source_model_sha256"])


def test_registration_requires_one_bounded_exact_selector():
    base = {"operation": "muscle.registration", "run_id": RUN, "state_index": 55,
            "motion_sha256": "1"*64, "mapping_revision_sha256": "2"*64}
    assert REQUEST.validate_python({**base, "actuator_id": 0}).actuator_id == 0
    for selector in ({}, {"actuator_id": 0, "display_node": 239}, {"actuator_id": "0"},
                     {"display_node": 239, "state_index": 55.0}, {"group_id": "bad"}, {"actuator_id": 0, "limit": 17}):
        with pytest.raises(ValidationError):
            REQUEST.validate_python({**base, **selector})


@pytest.mark.skipif(not os.environ.get("HMM_LAB_MUSCLE_CROSSWALK"), reason="real installation required")
def test_v3_keeps_candidate_routes_out_of_display_links():
    installed = registry()
    analytics = installed.whole.muscles
    context = analytics.context(UUID(RUN))
    data = context[1]
    if data.get("coverage_revision") != 3:
        pytest.skip("v3 crosswalk required")
    rows = {r["exact_name"]: r for r in data["rows"]}
    for name, family, side, digit in (
        ("QL_post_I_1-L3_r", "quadratus lumborum", "right", None),
        ("LD_T12_l", "latissimus dorsi", "left", None),
        ("FDPR_r", "flexor digitorum profundus", "right", 4),
        ("addmagIsch_l", "adductor magnus", "left", None),
        ("multifidus_L2_T12", "multifidus", "unknown", None),
    ):
        row = rows[name]
        assert row["registration_review"]["family"] == family
        assert row["side"] == side and row["canonical"]["digit"] == digit
        assert row["group"] is None and not row["usable"]["color"] and not row["display_assets"]
        assert all(c["side"] in (side, "unknown") and c["status"] == "CANDIDATE" for c in row["concept_membership"])
    assert rows["PECM3_r"]["registration_review"]["acceptance"]["concepts"] == []
    assert len([r for r in rows.values() if r["side"] == "unknown"]) == 52
    malformed = {**rows["LD_T12_l"], "exact_name": "fake_LD_T12_l",
                 "canonical": {**rows["LD_T12_l"]["canonical"], "stem": "fake_LD_T12"}}
    from registration_crosswalk import find_family

    files = rows["LD_T12_l"]["registration_review"]["model_xml_sha256"]
    assert find_family(malformed, {}, files)[0] is None
