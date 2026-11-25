"""Focused tests for local provisioning and source-aware relationship retrieval."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest


LAB = Path(__file__).resolve().parents[1] / "scripts/anatomy_lab"


def test_membership_pins_preserve_content_across_zip_timestamps(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB))
    from provision import membership

    content = b"# original version stamp\nFMA1\tpart_of\tFJ1\n"
    expected = {"path": "FMA2Obj.txt", "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest()}

    def compressed(year, data):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(ZipInfo(expected["path"], (year, 1, 1, 0, 0, 0)), data)
        return buffer.getvalue()

    a, b = (compressed(year, content) for year in (2024, 2026))
    assert a != b
    assert membership(a, expected) == membership(b, expected) == content
    with pytest.raises(ValueError, match="contents changed"):
        membership(compressed(2026, content.replace(b"FJ1", b"FJ2")), expected)


def test_direct_edge_sources_keep_inference_unknown(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LAB))
    from anatomy_lab import REQUEST, Registry

    data = {
        "schema_version": 1, "manifest": {"inferred_43i_coverage": "PARTIAL"},
        "sources": [{"id": "archive", "version": "archived"}, {"id": "live", "version": "4.3i"}],
        "concepts": [{"fma_id": i, "label": f"test {i}", "source_id": "archive"} for i in (1, 2)],
        "meshes": [], "components": [],
        "relations": [
            {"subject_fma": 1, "object_fma": 2, "predicate": "part_of",
             "source_predicate": "regional_part_of", "source_id": "archive", "inferred": False},
            {"subject_fma": 1, "object_fma": 2, "predicate": "part_of", "source_id": "live", "inferred": None},
        ],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(data))
    atlas = Registry(catalog, tmp_path)
    for source_id, inferred, predicate in (("archive", False, "regional_part_of"), ("live", None, "part_of")):
        response = atlas.call(REQUEST.validate_python({
            "operation": "anatomy.relationships", "concept": "FMA1", "source_id": source_id,
        }))
        (row,) = response["relationships"]
        assert row["source_predicate"] == predicate and row["inferred"] is inferred
    result = atlas.call(REQUEST.validate_python({
        "operation": "anatomy.relationships", "concept": "FMA2", "direction": "in", "include_labels": True,
    }))
    assert {row["related_concept"]["id"] for row in result["relationships"]} == {"FMA1"}
    parent = REQUEST.validate_python({
        "operation": "anatomy.relationships", "concept": "FMA1", "include_labels": True,
    })
    with ThreadPoolExecutor(max_workers=4) as executor:
        for actual in executor.map(atlas.call, [parent] * 24):
            assert [edge["related_concept"]["id"] for edge in actual["relationships"]] == ["FMA2", "FMA2"]
    assert atlas.coverage()["4.3i_anatomical_edges"] == "PARTIAL"


@pytest.fixture
def composite(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LAB))
    from anatomy_lab import REQUEST, Registry, canonical, digest

    meshes = tmp_path / "meshes"
    meshes.mkdir()
    pack_dir = tmp_path / "site/full/site/packs"
    pack_dir.mkdir(parents=True)
    pack = b"glTF" + bytes(24)
    (pack_dir / "pack-00.glb").write_bytes(pack)
    ids = ["FJ1", "FJ2"] + [f"FJ{i}" for i in range(10, 235)]
    mesh_bytes = b"source geometry"
    sha = digest(mesh_bytes)
    (meshes / "FJ1.obj").write_bytes(mesh_bytes)
    # FJ2 has a record and a display pack, while its source OBJ is missing.
    (pack_dir / "manifest.json").write_bytes(canonical({
        "format": "hmm-glb-packs/2", "source_sha256": digest(canonical(dict.fromkeys(ids, sha))),
        "original_glb_sha256": digest(pack),
        "packs": {"pack-00.glb": {"presets": [], "parts": ids, "bytes": len(pack), "sha256": digest(pack)}},
    }))
    versions = ("bp3d_43_components", "bp3d_43i_components")
    old = {"fma_id": 1, "fj_id": "FJ1", "mapping": "is_a", "source_id": versions[0]}
    data = {
        "schema_version": 1, "manifest": {"atlas_id": "BodyParts3D", "version": "4.3"},
        "sources": [{"id": "mesh", "version": "4.3"}, {"id": versions[0], "version": "4.3"},
                    {"id": versions[1], "version": "4.3i"}],
        "concepts": [{"fma_id": i, "label": "<b>Source label</b>" if i == 1 else f"Concept {i}",
                      "source_id": "mesh"} for i in (1, 2, 3)],
        "meshes": [{"fj_id": fj, "fma_id": 2, "pinned_filename_fma_id": 2, "bp_id": "BP1",
                    "obj_concept_id": "FMA3" if fj == "FJ1" else "FMA2",
                    "obj_representation_id": "BP2", "source_id": "mesh",
                    "bytes": len(mesh_bytes), "sha256": sha} for fj in ids],
        "components": [old, old, {**old, "source_id": versions[1]},
                       {**old, "fj_id": "FJ2", "source_id": versions[1]},
                       {**old, "fj_id": "FJ3", "source_id": versions[1]},
                       *[{**old, "fma_id": 3, "fj_id": fj} for fj in ids]],
        "relations": [],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_bytes(canonical(data))
    atlas = Registry(catalog, meshes)

    def call(operation, **kwargs):
        return atlas.call(REQUEST.validate_python({"operation": operation, **kwargs}))

    representation = {"dataset": "BodyParts3D", "mesh_version": "4.3", "membership_version": "4.3+4.3i"}
    return atlas, call, representation, pack_dir


def test_composite_resolution_and_scene(composite):
    _, call, representation, _ = composite
    fields = {"concept": "FMA1", "representation": representation, "limit": 2}
    first = call("anatomy.resolve", **fields)
    second = call("anatomy.resolve", **fields, offset=first["next_offset"])
    assert first["concept"]["label"] == "<b>Source label</b>"
    assert first["coverage"] == "PARTIAL"
    assert first["counts"] == {"members": 3, "renderable": 1, "missing_source": 2, "missing_display": 1,
                               "fma_conflict": 1, "bp_conflict": 2, "unresolved_identity": 1}
    assert [m["fj_id"] for m in first["members"] + second["members"]] == ["FJ1", "FJ2", "FJ3"]
    assert len(first["members"][0]["memberships"]) == 2 and second["next_offset"] is None
    assert first["selection_sha256"] == second["selection_sha256"]
    assert list(first["packs"]) == ["pack-00.glb"] and second["packs"] == {}
    assert call("anatomy.search", query="FMA1", representation=representation)["concept"]["visual_membership_count"] == 3
    assert call("anatomy.resolve", **{**fields, "concept": "FMA99"})["status"] == "unknown"
    assert call("anatomy.resolve", **{**fields, "concept": "FMA2"})["coverage"] == "UNAVAILABLE"
    scene = call("scene.create", selection=["FMA1"], representation=representation)
    assert scene["scene"]["composite"]["selection_sha256"] == first["selection_sha256"]
    assert call("scene.export", scene=scene["scene"]) == scene
    assert call("scene.select", scene=scene["scene"], selection=["FMA1"], representation=representation) == scene
    scene["scene"]["composite_view"]["inspected_fj"] = "FJ2"
    assert call("scene.export", scene=scene["scene"])["status"] == "integrity_error"


def test_composite_limits_and_cache_mismatch(composite):
    from pydantic import ValidationError

    atlas, call, representation, pack_dir = composite
    fields = {"concept": "FMA3", "representation": representation}
    first = call("anatomy.resolve", **fields, limit=200)
    last = call("anatomy.resolve", **fields, limit=200, offset=first["next_offset"])
    ids = [m["fj_id"] for m in first["members"] + last["members"]]
    assert ids == sorted(set(ids)) and len(ids) == 227 and last["next_offset"] is None
    with pytest.raises(ValidationError):
        call("anatomy.resolve", **fields, limit=201)
    with pytest.raises(ValidationError):
        call("anatomy.resolve", **{**fields, "representation": {**representation, "mesh_version": "4.4"}})
    scene = call("scene.create", selection=["FMA1"], representation=representation)["scene"]
    good_hash = scene["composite"]["asset_manifest_sha256"]
    scene["composite"]["asset_manifest_sha256"] = "0" * 64
    assert call("scene.export", scene=scene)["status"] == "integrity_error"

    scene["composite"]["asset_manifest_sha256"] = good_hash
    record = call("anatomy.resolve", concept="FMA1", representation=representation)["packs"]["pack-00.glb"]
    path = pack_dir / "pack-00.glb"
    path.write_bytes(bytes(path.stat().st_size))
    with pytest.raises(ValueError, match="bytes do not match"):
        atlas.pack_bytes("pack-00.glb", record["sha256"])
    with pytest.raises(ValueError):
        atlas.pack_bytes("../pack-00.glb", record["sha256"])
    path.unlink()
    assert call("scene.export", scene=scene)["status"] == "integrity_error"

def test_mesh_identity_keeps_competing_claims_and_membership_separate(composite):
    _, call, representation, _ = composite
    response = call("anatomy.identify", mesh="FJ1", representation=representation, limit=2)
    assert response["mesh"]["fma_id"] is None
    assert response["mesh"]["identity_status"] == "DISPUTED"
    assert response["bp_conflict"] and response["candidate_count"] == 3
    claims, obj = response["candidates"]
    assert claims["id"] == "FMA2" and claims["identity_claims"] == ["master_fma_id", "pinned_filename_fma_id"]
    assert obj["id"] == "FMA3" and obj["identity_claims"] == ["obj_concept_id"]
    page = call("anatomy.identify", mesh="FJ1", representation=representation, offset=response["next_offset"])
    member, = page["candidates"]
    assert member["id"] == "FMA1" and not member["identity_claims"]
    assert len(member["memberships"]) == 2 and page["next_offset"] is None
    assert call("anatomy.identify", mesh="FJ999", representation=representation)["status"] == "unknown"


def test_composite_display_roundtrip_preserves_original_document(composite):
    _, call, representation, _ = composite
    original = call("scene.create", selection=["FMA1"], representation=representation)
    scene = original["scene"]
    assert set(scene["composite_view"]) == {"isolated", "context_fj_ids", "inspected_fj"}
    view = {**scene["composite_view"], "hidden_layers": ["vein", "bone", "vein"], "context_opacity": .55}
    changed = call("scene.export", scene={**scene, "composite_view": view})
    assert changed["scene"]["composite_view"]["hidden_layers"] == ["bone", "vein"]
    assert changed["scene"]["composite_view"]["context_opacity"] == .55
    assert changed["scene_sha256"] != original["scene_sha256"]
    assert changed["scene"]["composite"] == scene["composite"]
    assert call("scene.export", scene=changed["scene"]) == changed


@pytest.mark.parametrize("kind", ["filename", "source_sha256", "duplicate_fj"])
def test_composite_rejects_invalid_display_index(composite, kind):
    _, call, representation, pack_dir = composite
    path = pack_dir / "manifest.json"
    index = json.loads(path.read_bytes())
    if kind == "filename":
        index["packs"]["../pack-00.glb"] = index["packs"].pop("pack-00.glb")
    elif kind == "source_sha256":
        index["source_sha256"] = "0" * 64
    else:
        index["packs"]["pack-00.glb"]["parts"].append("FJ1")
    path.write_text(json.dumps(index))
    assert call("anatomy.resolve", concept="FMA1", representation=representation)["status"] == "integrity_error"
