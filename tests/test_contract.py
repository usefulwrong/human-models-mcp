import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml
from pydantic import ValidationError

from human_models_mcp import core
from human_models_mcp.catalog import model_card
from human_models_mcp.registry import SweepParameters, ForwardParameters, discover, home
from human_models_mcp.results import get_artifact, get_run


@pytest.mark.parametrize("params", [
    {"samples": True}, {"samples": 2}, {"samples": 102}, {"samples": "9"},
    {"start_rad": float("nan")}, {"end_rad": float("inf")}, {"start_rad": 2.0, "end_rad": 1.0},
    {"muscle": ""}, {"render": "true"}, {"host_path": "/etc/passwd"}, {"seed": 42},
])
def test_parameter_boundary(params):
    with pytest.raises(ValidationError):
        SweepParameters.model_validate(params)


@pytest.mark.parametrize("params", [{"steps": 0}, {"steps": 26}, {"steps": True}, {"steps": "10"},
                                      {"excitation": -0.1}, {"excitation": 1.1}, {"excitation": float("nan")},
                                      {"command": "echo unsafe"}])
def test_forward_parameter_boundary(params):
    with pytest.raises(ValidationError):
        ForwardParameters.model_validate(params)


def test_registry_extension_and_quarantine(tmp_path):
    source = home() / "scenarios/elbow_sweep"
    folder = tmp_path / "new_sweep"
    shutil.copytree(source, folder)
    path = folder / "scenario.yaml"
    document = yaml.safe_load(path.read_text())
    document["id"] = "new_sweep"
    path.write_text(yaml.safe_dump(document))
    assert discover(tmp_path)["scenarios"][0]["id"] == "new_sweep"
    document["backend"] = "shell"
    path.write_text(yaml.safe_dump(document))
    assert discover(tmp_path)["scenarios"] == []
    assert "backend" in discover(tmp_path)["quarantined"][0]["message"]
    path.write_text("!!python/object/apply:os.system ['echo unsafe']")
    assert discover(tmp_path)["quarantined"]
    path.write_text("x" * 16385)
    assert "16 KiB" in discover(tmp_path)["quarantined"][0]["message"]
    shutil.rmtree(folder)
    folder.symlink_to(source)
    assert "symlink" in discover(tmp_path)["quarantined"][0]["message"]


def test_catalog_is_lazy():
    script = "from human_models_mcp.server import list_models; import sys; list_models(); assert 'mujoco' not in sys.modules; assert 'numpy' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", script], capture_output=True).returncode == 0


def test_source_search_is_offline_and_attributed():
    from human_models_mcp.sources import search_sources
    result = search_sources("BIClong_r")
    assert result["status"] == "ok" and result["backend"] == "sqlite_fts5" and result["offline"]
    match = next(m for m in result["matches"] if m["id"] == "BIClong_r")
    assert match["evidence_type"] == "upstream_model_identifier" and len(match["source_sha256"]) == 64
    assert match["license"] == "Apache-2.0" and result["model_revision"] in match["source_url"]
    assert search_sources("zzzzunknownanatomy")['matches'] == []
    assert search_sources('" OR 1=1 --')["status"] == "ok"
    assert search_sources("*" * 5)["status"] == "invalid_input"
    assert search_sources("muscle", True)["status"] == "invalid_input"


def test_offline_bundle_detects_tampering_and_traversal(tmp_path):
    import runpy
    verify = runpy.run_path(str(home() / "scripts/verify_bundle.py"))["verify"]
    (tmp_path / "image.tar").write_bytes(b"test archive")
    manifest = {"image_id": "sha256:" + "a" * 64, "image_tag": "human-models-mcp-night-runtime:local",
                "files": {"image.tar": hashlib.sha256(b"test archive").hexdigest()}}
    (tmp_path / "bundle.json").write_text(json.dumps(manifest))
    assert verify(tmp_path)["image_id"] == manifest["image_id"]
    (tmp_path / "image.tar").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        verify(tmp_path)
    manifest["files"] = {"../outside": "anything"}
    (tmp_path / "bundle.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe"):
        verify(tmp_path)


def test_handover_ignores_stale_evidence_when_checks_fail(tmp_path):
    import runpy
    write = runpy.run_path(str(home() / "scripts/write_report.py"))["main"]
    write.__globals__["ROOT"] = tmp_path
    reports = tmp_path / "reports"
    reports.mkdir()
    gates = {name: {"status": "fail", "required": name != "gpu-smoke"}
             for name in ("e2e", "package", "doctor", "demo", "gpu-smoke")}
    verdict = {"release_status": "BLOCKED", "gates": gates, "timestamp": "test", "head": "no_git_repository",
               "image_id": None, "source_sha256": "a" * 64}
    (reports / "RELEASE_CHECK.json").write_text(json.dumps(verdict))
    (reports / "e2e.json").write_text("stale invalid evidence must not be read")
    write()
    assert "BLOCKED" in (reports / "OVERNIGHT_REPORT.md").read_text()
    assert (reports / "CHANGED_FILES.txt").is_file()


@pytest.mark.parametrize("content", ["not: [valid", "validation_level: experimentally_validated",
                                       "!!python/object/apply:os.system ['echo unsafe']", "x" * 16385])
def test_invalid_validation_is_quarantined(tmp_path, content):
    folder = tmp_path / "elbow_sweep"
    shutil.copytree(home() / "scenarios/elbow_sweep", folder)
    (folder / "validation.yaml").write_text(content)
    found = discover(tmp_path)
    assert found["scenarios"] == [] and found["quarantined"][0]["id"] == "elbow_sweep"


def test_model_integrity(tmp_path, monkeypatch):
    original = home()
    lock = json.loads((original / "models.lock.json").read_text())
    lock["files"] = [{"path": "ms_human_700/asset.xml", "sha256": hashlib.sha256(b"expected").hexdigest(), "size": 8}]
    lock["asset_sha256"] = hashlib.sha256(json.dumps(lock["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (tmp_path / "models.lock.json").write_text(json.dumps(lock))
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    assert model_card(True)["status"] == "not_installed"
    asset = tmp_path / "models/ms_human_700/asset.xml"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"expected")
    assert model_card(True)["status"] == "available"
    asset.write_bytes(b"tampered")
    assert model_card(True)["status"] == "unavailable"


def test_result_traversal_and_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    run_id = "c8a52676-3880-49e4-ad12-2b7f5a965f2e"
    output = tmp_path / "results" / run_id
    output.mkdir(parents=True)
    data = "a,b\n1,2\n"
    (output / "series.csv").write_text(data)
    manifest = {"artifacts": {"series.csv": {"sha256": hashlib.sha256(data.encode()).hexdigest(), "mime_type": "text/csv"}}}
    (output / "manifest.json").write_text(json.dumps(manifest))
    assert get_artifact(run_id, "series.csv")["data"] == data
    assert get_artifact(run_id, "../../etc/passwd")["status"] == "invalid_input"
    assert get_run("../../etc/passwd")["status"] == "invalid_input"
    (output / "series.csv").write_text("corrupt")
    assert get_artifact(run_id, "series.csv")["status"] == "integrity_error"
    (output / "series.csv").unlink()
    assert get_artifact(run_id, "series.csv")["status"] == "integrity_error"
    (output / "series.csv").symlink_to(output / "manifest.json")
    assert get_artifact(run_id, "series.csv")["status"] == "invalid_input"


def test_executor_busy_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    with core.executor_lock() as acquired:
        assert acquired
        assert core.get_joint_info("ms_human_700")["status"] == "busy"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 90)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert core.worker({"operation": "inspect"})["status"] == "failed"


def test_failed_run_keeps_provenance_without_validation_claim(tmp_path, monkeypatch):
    original = home()
    for name in ("scenarios", "models", "models.lock.json", "requirements.lock"):
        (tmp_path / name).symlink_to(original / name)
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))

    def fail(request):
        initial = get_run(request["run_id"])
        assert initial["status"] == "running"
        assert initial["scientific"]["validation_level"] == "unvalidated"
        return {"status": "failed", "error": {"code": "test_failure", "message": "injected worker failure"}}

    monkeypatch.setattr(core, "worker", fail)
    result = core.run_scenario("elbow_sweep")
    assert result["status"] == "failed" and result["outputs"]["metrics"] == []
    assert result["scientific"]["validation_level"] == "unvalidated"
    assert result["model"]["revision"] and result["model"]["asset_sha256"]
    assert get_run(result["run_id"]) == result


def test_untrusted_scenarios_rejected_before_worker():
    assert core.run_scenario("../../etc/passwd")["status"] == "unsupported"
    assert core.run_scenario("elbow_sweep", {"samples": 10000})["status"] == "invalid_input"
    assert core.run_scenario("elbow_sweep", {}, "x" * 129)["status"] == "invalid_input"


def test_store_quota(tmp_path, monkeypatch):
    original = home()
    (tmp_path / "scenarios").symlink_to(original / "scenarios")
    monkeypatch.setenv("HUMAN_MODELS_HOME", str(tmp_path))
    for i in range(200):
        folder = tmp_path / "results" / str(i)
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}")
    assert core.run_scenario("elbow_sweep")["status"] == "resource_limit"


def test_skills_match_tools():
    from human_models_mcp.server import mcp
    import asyncio
    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"list_models", "list_scenarios", "run_scenario", "get_result", "get_artifact"} <= tools
    for name in ("human-models-mcp", "scientific-interpretation", "scenario-authoring", "scientific-visualization"):
        text = (home() / "skills" / name / "SKILL.md").read_text()
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["name"] == name and meta["description"]
    assert not Path("/app/.agent-input").exists() or home() != Path("/app")
