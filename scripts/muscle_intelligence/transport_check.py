"""Use the official MCP SDK through stdio, independent NPZ reads and live local HTTP."""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import Client, StdioServerParameters
import numpy as np

RUN = "14f5e412-a31e-4b72-b008-278bd8c96ce3"


def http(origin, op, fields):
    with urlopen(Request(origin + "/api/query", json.dumps({"operation": op, **fields}).encode(),
                         {"Content-Type": "application/json"}), timeout=30) as response:
        return json.load(response)


async def audit_all(parity, source, manifest, arrays, out, elapsed):
    def sha(path):
        return sha256(path.read_bytes()).hexdigest()

    names = json.loads((source / "actuators.json").read_bytes())["actuators"]
    assert len(names) == len(set(r["name"] for r in names)) == 700
    expected = {k: v for k, v in arrays.items() if k != "time_s"}
    clock = arrays["time_s"]
    power = expected["power_W"]
    expected["force_magnitude_N"] = abs(expected["force_N"])
    expected["work_J"] = np.vstack([np.zeros(700), np.cumsum(
        (power[:-1] + power[1:]) * (np.diff(clock)[:, None] / 2), axis=0)])
    rank = {r["actuator"]: r["signed_mechanical_work_J"] for r in
            json.loads((source / "muscle_ranking.json").read_bytes())["actuators"]}
    rows = []
    offset = 0
    while offset is not None:
        listed = await parity("muscle.search", offset=offset, limit=40, brief=True)
        assert listed["count"] == 700
        assert [(r["id"], r["exact_name"]) for r in listed["rows"]] == [
            (r["id"], r["name"]) for r in names[offset:offset + 40]]
        offset = listed["next_offset"]
    for row in names:
        found = await parity("muscle.resolve", query=row["name"], brief=True)
        assert [(r["id"], r["exact_name"]) for r in found["rows"]] == [(row["id"], row["name"])]
        timing = elapsed[-1]
        rows.append({"id": row["id"], "exact_name": row["name"], "mapping_status": found["mapping_status"],
                     "fields": {}, "resolve_ms": {k: timing[k] for k in ("mcp_ms", "http_ms")}})
    for metric, values in expected.items():
        for start in range(0, 700, 16):
            ids = list(range(start, min(start + 16, 700)))
            reply = await parity("muscle.timeseries", actuator_ids=ids, metric=metric)
            timing = elapsed[-1]
            assert reply["state_indices"] == list(range(111)) and reply["next_offset"] is None
            assert len(set(reply["state_sha256"])) == 111
            np.testing.assert_array_equal(reply["time_s"], clock)
            for i, series in enumerate(reply["series"]):
                idx = series["actuator_id"]
                assert idx == ids[i] and series["exact_name"] == names[idx]["name"]
                signal = np.asarray(series["values"])
                np.testing.assert_array_equal(signal, values[:, idx])
                stats = {"sample_count": len(signal), "min": float(signal.min()), "max": float(signal.max()),
                         "finite": bool(np.isfinite(signal).all()), "unit": reply["unit"],
                         "batch_latency_ms": {k: timing[k] for k in ("mcp_ms", "http_ms")}}
                assert stats["finite"]
                if metric == "work_J":
                    stats["full_integrator_work_J"] = reply["full_integrator_work_J"][i]
                    assert stats["full_integrator_work_J"] == rank[series["exact_name"]]
                rows[idx]["fields"][metric] = stats
    for row in rows:
        assert len(row["fields"]) == len(expected)
        row["status"] = "PASS"
    artifacts = {}
    for name in ("manifest.json", "actuators.json", "muscle_ranking.json", "trajectory.npz",
                 *manifest["outputs"]["muscles"]["chunks"]):
        artifacts[name] = sha(source / name)
        if name != "manifest.json":
            assert artifacts[name] == manifest["artifacts"][name]["sha256"]
    assets, offset = {}, 0
    while offset is not None:
        page = await parity("muscle.search", inventory="display", offset=offset, limit=40)
        assets.update({a["display_copy"]: a for a in page["assets"]})
        offset = page["next_offset"]
    for node, asset in assets.items():
        desc = await parity("muscle.describe", display_node=node)
        assert desc["asset"]["mesh_id"] == asset["mesh_id"]
        assert bool(desc["rows"]) == bool(asset.get("group_id"))
        assert desc["mapping_status"] != "GEOMETRY_ONLY" or not desc["rows"]
    summaries = {k: dict(zip(("p50", "p95", "max"),
                              np.percentile([e[k] for e in elapsed], (50, 95, 100)).tolist(), strict=True))
                 for k in ("mcp_ms", "http_ms")}
    (out / "ALL_ACTUATOR_SIGNAL_AUDIT.json").write_text(json.dumps(
        {"status": "PASS", "run_id": RUN, "samples": 111, "artifact_sha256": artifacts,
         "audit_source_sha256": sha(Path(__file__)), "latency_ms_all_calls": summaries,
         "transport": "Official MCP SDK over stdio, live HTTP and independent NumPy reads",
         "display_node_ids_resolved": sorted(assets), "rows": rows}, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS {len(rows)} exact native identities, {len(expected)} fields at all 111 states, "
          f"{len(assets)} display nodes over both transports", flush=True)


async def check(origin, out):
    source = Path(os.environ["HMM_LAB_WHOLE_RESULTS"]) / RUN
    result = json.loads((source / "manifest.json").read_bytes())
    files = result["outputs"]["muscles"]["chunks"]
    metrics = ("time_s", "activation", "excitation", "force_N", "length_m", "velocity_m_per_s", "power_W")
    data = {k: [] for k in metrics}
    elapsed = []
    for name in files:
        with np.load(source / name, allow_pickle=False) as values:
            for key in metrics:
                data[key].append(values[key])
    data = {k: np.concatenate(v) for k, v in data.items()}
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "lab_mcp"], env=dict(os.environ)),
                      read_timeout_seconds=60) as client:

        async def parity(op, run_id=RUN, **fields):
            args = {"run_id": run_id, **fields}
            t = perf_counter()
            reply = await client.call_tool("anatomy_lab", {"request": {"operation": op, **args}})
            assert not reply.is_error, reply.content
            mcp_ms = (perf_counter() - t) * 1000
            t = perf_counter()
            web = http(origin, op, args)
            elapsed.append({"operation": op, "mcp_ms": mcp_ms, "http_ms": (perf_counter() - t) * 1000})
            assert reply.structured_content == web
            return web

        motion = await parity("whole.open")
        sha = motion["motion_sha256"]
        assert len(motion["motion"]["frames"]) == 111
        record = {}
        for node, group, source_names in (
            (239, "pectoralis_major:right", ["PECM1_r", "PECM2_r", "PECM3_r"]),
            (237, "pectoralis_major:left", ["PECM1_l", "PECM2_l", "PECM3_l"]),
            (367, "triceps_brachii:right", ["TRIlong_r", "TRIlat_r", "TRImed_r"]),
            (364, "triceps_brachii:left", ["TRIlong_l", "TRIlat_l", "TRImed_l"]),
            (402, None, []),
            (457, "soleus:right", ["soleus_r"]),
        ):
            if group is None:
                orphan = await parity("muscle.describe", display_node=node)
                assert orphan["mapping_status"] == "GEOMETRY_ONLY"
                chosen = {"mapping_revision_sha256": orphan["mapping_revision_sha256"], "display_node": node,
                          "isolate": True, "opacity": .55}
                selected_orphan = await parity("muscle.select", motion_sha256=sha, state_index=55, selection=chosen)
                assert selected_orphan["display_nodes"] == [node] and "sample" not in selected_orphan
                continue
            desc = await parity("muscle.describe", display_node=node, side=group.split(":")[1])
            assert desc["mapping_status"] == "REVIEWED_ANATOMICAL"
            assert [x["exact_name"] for x in desc["rows"]] == source_names
            assert desc["acceptance"]["muscle_driven"] == "NOT_ACHIEVED"
            assert desc["acceptance"]["external_control"] == "USED"
            assert desc["human_validation"] == "NOT_VALIDATED"
            entries = {}
            for metric in (*metrics[1:], "force_magnitude_N"):
                v = await parity("muscle.timeseries", group_id=group, metric=metric, phase_summary=True)
                assert v["state_indices"] == list(range(111))
                np.testing.assert_array_equal(v["time_s"], data["time_s"])
                expected = data["force_N" if metric == "force_magnitude_N" else metric]
                if metric == "force_magnitude_N":
                    expected = abs(expected)
                columns = []
                for row, path in zip(v["series"], desc["rows"], strict=True):
                    assert row["actuator_id"] == path["id"]
                    np.testing.assert_array_equal(row["values"], expected[:, path["id"]])
                    columns.append(expected[:, path["id"]])
                values = np.column_stack(columns)
                if v["aggregate"]:
                    agg = values.mean(axis=1) if metric in ("activation", "excitation") else values.sum(axis=1)
                    np.testing.assert_array_equal(v["aggregate"], agg)
                    assert v["phase_summary"]["bottom"]["mean_derived"] == agg[55]
                assert v["phase_summary"]["ascent"]["inclusive_state_bounds"] == [56, 110]
                entries[metric] = v
            group_activation = entries["activation"]
            one = await parity("muscle.timeseries", actuator_ids=[desc["rows"][0]["id"]],
                               start_s=data["time_s"][27], end_s=data["time_s"][55], stride=2, limit=5)
            assert one["state_indices"] == [27, 29, 31, 33, 35] and one["next_offset"] == 10
            assert one["series"][0]["values"] == [group_activation["series"][0]["values"][i] for i in one["state_indices"]]
            selected = {"mapping_revision_sha256": desc["mapping_revision_sha256"], "display_node": node,
                        "metric": "force_N", "actuator_id": None, "overlay": True}
            exact = await parity("muscle.select", motion_sha256=sha, state_index=55, selection=selected, publish=True)
            assert exact == await parity("muscle.selection")
            assert exact["sample"]["aggregate"][0] == entries["force_N"]["aggregate"][55]
            assert exact["overlay"]["value"] == group_activation["aggregate"][55]
            record[group] = {"description": desc, "entries": entries, "selection": exact}
        assert (await parity("muscle.describe", display_node=239, side="left"))["mapping_status"] == "UNMAPPED"
        assert (await parity("muscle.describe", display_node=0))["mapping_status"] == "UNMAPPED"
        assert (await parity("muscle.resolve", query="PECM10_r"))["mapping_status"] == "UNMAPPED"
        assert (await parity("muscle.search", query="pectoralis major"))["mapping_status"] == "AMBIGUOUS"
        assert (await parity("muscle.resolve", query="FMA45874"))["mapping_status"] == "CANDIDATE"
        unmapped = next(r for r in json.loads(Path(os.environ["HMM_LAB_MUSCLE_CROSSWALK"]).read_bytes())["rows"]
                        if r["status"] == "UNMAPPED")
        native_view = {"mapping_revision_sha256": selected["mapping_revision_sha256"],
                       "actuator_id": unmapped["id"]}
        bare = await parity("muscle.select", motion_sha256=sha, state_index=55, selection=native_view)
        assert bare["asset"] is None and not bare["display_nodes"] and "overlay" not in bare
        assert bare["sample"]["series"][0]["values"] == [data["activation"][55, unmapped["id"]]]
        bad = await parity("muscle.select", motion_sha256=sha, state_index=55,
                           selection={**native_view, "display_node": 239})
        assert bad["error"]["code"] == "integrity_error"
        bad = await parity("muscle.timeseries", group_id="pectoralis_major:right", end_s=55)
        assert bad["error"]["code"] == "integrity_error"
        bad = await parity("muscle.select", motion_sha256="0" * 64, state_index=55, selection=selected)
        assert bad["error"]["code"] == "integrity_error"
        bad = await parity("muscle.select", motion_sha256=sha, state_index=55,
                           selection={**selected, "mapping_revision_sha256": "0" * 64})
        assert bad["error"]["code"] == "integrity_error"
        bad = await parity("muscle.timeseries", run_id="ce5bde04-d3ba-4bd3-989d-0bfe33b49a43", actuator_ids=[0])
        assert bad["error"]["code"] == "unsupported"
        for fields in ({"actuator_ids": list(range(700))}, {"actuator_ids": [700]},
                       {"actuator_ids": [0], "script": "unsupported"}):
            mcp_invalid = await client.call_tool("anatomy_lab", {"request": {
                "operation": "muscle.timeseries", "run_id": RUN, **fields}})
            assert mcp_invalid.is_error
            try:
                http(origin, "muscle.timeseries", {"run_id": RUN, **fields})
            except HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("invalid typed request accepted")
        for path in ("/muscles_000.npz", "/api/whole/muscles_000.npz/" + "0" * 64, "/%2e%2e/AGENTS.md"):
            try:
                urlopen(origin + path, timeout=10)
            except HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError("unapproved file was served")
        restore = record["pectoralis_major:right"]
        saved = await parity("muscle.select", motion_sha256=sha, state_index=55,
                             selection=restore["selection"]["selection"], publish=True)
        bad = await parity("muscle.select", motion_sha256=sha, state_index=55,
                           selection=native_view, publish=True, if_match="0" * 64)
        assert bad["error"]["code"] == "integrity_error" and await parity("muscle.selection") == saved
        parallel = await asyncio.gather(*[
            asyncio.to_thread(http, origin, "muscle.select", {"run_id": RUN, "motion_sha256": sha,
                "state_index": i, "selection": native_view, "publish": True, "if_match": saved["selection_sha256"]})
            for i in (27, 83)])
        winner, = [item for item in parallel if item["status"] == "ok"]
        loser, = [item for item in parallel if item["status"] != "ok"]
        assert loser["error"]["code"] == "integrity_error"
        assert await parity("muscle.selection") == winner
        (out / "selection-race.json").write_text(json.dumps(parallel, indent=2), encoding="utf-8", newline="\n")
        await parity("muscle.select", motion_sha256=sha, state_index=55,
                     selection=restore["selection"]["selection"], publish=True)
        if "--full" in sys.argv:
            await audit_all(parity, source, result, data, out, elapsed)
        (out / "selection-controls.json").write_text(json.dumps({"orphan": selected_orphan, "native": bare}, indent=2), encoding="utf-8", newline="\n")
    (out / "transport.json").write_text(json.dumps(record, indent=2), encoding="utf-8", newline="\n")
    (out / "transport-timing.json").write_text(json.dumps(elapsed, indent=2), encoding="utf-8", newline="\n")
    print("PASS official stdio MCP == HTTP == native NPZ for five sided groups, seven metrics and all 111 states.")
    print("PASS exact view, signed vs magnitude, aggregation, phase bounds and invalid requests.")


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1], Path(sys.argv[2])))
