import asyncio
import csv
import hashlib
import importlib.util
import json
import re
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from human_models_mcp.registry import home, discover, TrackingParameters, WristParameters


def test_reference_reproduces_published_nonimpaired_table():
    from human_models_mcp.adapters.wrist import reference
    rows, metadata = reference()
    assert metadata["license"] == "CC0-1.0" and metadata["doi"] == "10.1371/journal.pone.0157346"
    article = ET.parse(home() / "benchmarks/nichols2016_wrist/article.xml")
    assert metadata["article_title"] == article.findtext("./front/article-meta/title-group/article-title")
    table = next(item for item in article.findall(".//table-wrap") if item.get("id") == "pone.0157346.t002")
    for tr in table.findall(".//tbody/tr")[:5]:
        cells = ["".join(item.itertext()).strip() for item in tr.findall("td")]
        for axis, column in (("extension", 1), ("ulnar_deviation", 4)):
            mean, sd = map(float, re.fullmatch(r"(-?[\d.]+) \(([\d.]+)\)", cells[column]).groups())
            row = next(item for item in rows if item["muscle"] == cells[0] and item["axis"] == axis)
            assert float(row["mean_m"]) == mean * .01 and float(row["sd_m"]) == sd * .01
            assert int(row["n_specimens"]) == 8


def test_new_scenarios_expose_actual_parameter_bounds():
    scenarios = {item["id"]: item for item in discover()["scenarios"]}
    assert {"wrist_benchmark", "elbow_tracking"} <= scenarios.keys()
    for scenario in scenarios.values():
        for name, value in scenario["defaults"].items():
            assert scenario["parameter_schema"]["properties"][name]["default"] == value
    props = scenarios["elbow_tracking"]["parameter_schema"]["properties"]
    assert props["target_rad"]["maximum"] == .6 and props["steps"]["maximum"] == 400
    assert TrackingParameters(steps=400, timestep_s=.001).steps == 400
    for parameters in ({"steps": 300}, {"target_rad": 2.0}, {"torque_Nm": 1.0}, {"command": "echo unsafe"}):
        with pytest.raises(ValidationError):
            TrackingParameters.model_validate(parameters)
    with pytest.raises(ValidationError):
        WristParameters.model_validate({"reference_id": "arbitrary_file"})


def test_real_wrist_benchmark_has_no_fitting(tmp_path):
    from human_models_mcp.adapters.wrist import benchmark
    scenario = next(item for item in discover()["scenarios"] if item["id"] == "wrist_benchmark")
    result = benchmark({"render": False}, tmp_path, scenario["validation"])
    assert result["coordinate_mode"] == "geometric_neutral_coupled_wrist"
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["fit_to_experimental_values"] is False
    assert max(abs(x) for x in comparison["neutral_geometric_angles_rad"]) < 1e-10
    rows = list(csv.DictReader((tmp_path / "series.csv").open()))
    assert len(rows) == 10 and max(float(row["jacobian_error_m_per_rad"]) for row in rows) < 1e-7
    for metric in result["metrics"][:2]:
        axis = metric["name"].removeprefix("rmse_")
        selected = [float(row["difference_m"]) for row in rows if row["axis"] == axis]
        assert abs(metric["value"] - (sum(x*x for x in selected)/len(selected))**.5) < 1e-12


def exporter():
    path = home() / "examples/mcp-client/artifacts.py"
    spec = importlib.util.spec_from_file_location("client_artifacts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_run


def test_client_export_rejects_traversal_and_existing_directory(tmp_path):
    async def unused(*args):
        raise AssertionError("invalid paths must fail before contacting server")
    with pytest.raises(ValueError, match="filename"):
        asyncio.run(exporter()(unused, {"status": "computed", "artifacts": {"../escape": {"bytes": 1}}}, tmp_path / "out"))
    assert not (tmp_path / "out").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(exporter()(unused, {"status": "computed", "artifacts": {}}, tmp_path))


def test_client_export_rejects_changed_bytes(tmp_path):
    async def changed(*args):
        return {"status": "ok", "encoding": "utf-8", "data": "wrong"}
    run = {"status": "computed", "run_id": "test", "artifacts": {"data.csv": {"bytes": 5, "sha256": hashlib.sha256(b"right").hexdigest()}}}
    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(exporter()(changed, run, tmp_path / "out"))
    assert not (tmp_path / "out/index.html").exists()


def test_supported_unknown_and_known_unsupported_have_distinct_evidence():
    from human_models_mcp.server import get_model_capabilities
    assert get_model_capabilities("ms_human_700", "joint_pd_tracking")["status"] == "available"
    assert get_model_capabilities("ms_human_700", "defecation")["reason"] == "known_unsupported"
    assert get_model_capabilities("ms_human_700", "invented_quantity")["reason"] == "unknown_quantity"
