"""Exercise the registration contract over official stdio MCP and live HTTP."""

import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError

from mcp import Client, StdioServerParameters

from transport_check import RUN, http


async def check(origin, out):
    crosswalk = json.loads(Path(os.environ["HMM_LAB_MUSCLE_CROSSWALK"]).read_bytes())
    spine = next(row for row in crosswalk["rows"] if row["region"] == "spine" and row["status"] == "UNMAPPED")
    pectoral = next(row for row in crosswalk["rows"] if row["exact_name"] == "PECM1_r")
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "lab_mcp"], env=dict(os.environ))) as client:
        async def parity(op, **fields):
            body = {"run_id": RUN, **fields}
            mcp = await client.call_tool("anatomy_lab", {"request": {"operation": op, **body}})
            assert not mcp.is_error
            result = http(origin, op, body)
            assert result == mcp.structured_content
            return result

        opened = await parity("whole.open")
        first = await parity("muscle.describe", display_node=239)
        fields = {"motion_sha256": opened["motion_sha256"], "mapping_revision_sha256": first["mapping_revision_sha256"],
                  "state_index": 55}

        async def registration(**extra):
            return await parity("muscle.registration", **{**fields, **extra})

        controls = {
            "pectoral": {"display_node": 239, "actuator_id": pectoral["id"], "metric": "force_N", "isolate": True},
            "deep-shoulder": {"display_node": 460, "overlay": True, "isolate": True},
            "lower-leg": {"display_node": 457, "overlay": True, "isolate": True},
            "negative-oblique": {"display_node": 402, "isolate": True},
            "unmapped-spinal": {"actuator_id": spine["id"]},
        }
        expected = ["REVIEWED_ANATOMICAL", "REVIEWED_ANATOMICAL", "REVIEWED_ANATOMICAL", "GEOMETRY_ONLY", "UNMAPPED"]
        views, groups = {}, {}
        for (label, selection), status in zip(controls.items(), expected, strict=True):
            selector = ({"actuator_id": selection["actuator_id"]} if "actuator_id" in selection else
                        {"display_node": selection["display_node"]})
            result = await registration(**selector)
            assert (result["mapping_status"] == status and result["crosswalk_revision"] == 3
                    and result["frame"] == opened["motion"]["frames"][55]
                    and result["deformation_validation"] == result["attachment_footprint"] == "NOT_VERIFIED")
            view = await parity("muscle.select", state_index=55, motion_sha256=fields["motion_sha256"],
                                selection={"mapping_revision_sha256": fields["mapping_revision_sha256"], **selection})
            assert view["frame"] == result["frame"] and view["motion_sha256"] == result["motion_sha256"]
            curves = {}
            if label == "negative-oblique":
                assert result["rows"] == [] and "sample" not in view and "overlay" not in view
                assert view["display_nodes"] == [402]
            else:
                assert result["rows"] and "sample" in view
                ids = ({"actuator_ids": [selection["actuator_id"]]} if "actuator_id" in selection else
                       {"group_id": view["group"]["group_id"]})
                metric = selection.get("metric", "activation")
                curves[metric] = await parity("muscle.timeseries", metric=metric, **ids, phase_summary=True)
                for sampled, curve in zip(view["sample"]["series"], curves[metric]["series"], strict=True):
                    assert sampled["values"] == [curve["values"][55]]
                if selection.get("overlay"):
                    groups[view["group"]["group_id"]] = {"selection": view, "entries": curves}
            views[label] = {**view, "registration": result, "curves": curves}

        left = await registration(group_id="pectoralis_major:left", side="left", limit=1)
        assert left["count"] == 3 and left["next_offset"] == 1 and left["rows"][0]["exact_name"] == "PECM1_l"
        part = await registration(group_id="pectoralis_major:left", side="left", limit=1, offset=2)
        assert part["rows"][0]["exact_name"] == "PECM3_l" and part["rows"][0]["registration_review"]["fma"] == "CANDIDATE"
        assert (await registration(display_node=239, side="left"))["mapping_status"] == "UNMAPPED"
        assert (await registration(display_node=4095))["mapping_status"] == "UNMAPPED"
        for extra in ({"state_index": 111}, {"motion_sha256": "0" * 64}, {"mapping_revision_sha256": "0" * 64}):
            assert (await registration(actuator_id=0, **extra))["error"]["code"] == "integrity_error"
        for invalid in ({}, {"actuator_id": 0, "display_node": 239}, {"actuator_id": "0"},
                        {"group_id": "pectoralis_major:right", "limit": 17}, {"display_node": -1}):
            body = {"run_id": RUN, **fields, **invalid}
            bad = await client.call_tool("anatomy_lab", {"request": {"operation": "muscle.registration", **body}})
            assert bad.is_error
            try:
                http(origin, "muscle.registration", body)
            except HTTPError as error:
                assert error.code == 400
            else:
                raise AssertionError("malformed registration selector succeeded")

        if sha := os.environ.get("HMM_LAB_REGISTRATION_EVIDENCE_SHA"):
            evidence = {"evidence_frame": "mujoco_world_m", "evidence_revision_sha256": sha}
            for node in (237, 239, 228, 229, 495, 496, 351, 460, 348, 457, 290, 402):
                pilot = await registration(display_node=node, **evidence)
                inspection = pilot["evidence"]
                assert inspection["status"] == "NOT_VERIFIED"
                assert inspection["frame"] == pilot["frame"]
                assert inspection["pilot"]["node"] == node and inspection["revision_sha256"] == sha
                if node in (290, 402):
                    assert inspection["pilot"]["association"] == "GEOMETRY_ONLY" and inspection["routes"] == []
                else:
                    assert inspection["bones"] and inspection["routes"]
            for index in (0, 27, 55, 83, 110):
                info = await registration(display_node=239, state_index=index, **evidence)
                assert info["evidence"]["routes"][0]["state_index"] == index
            for selector in ({"display_node": 239, "side": "unknown"}, {"display_node": 4095},
                             {"actuator_id": spine["id"]}):
                info = await registration(**selector, **evidence)
                assert info["evidence"]["status"] == "OUT_OF_SCOPE"
            stale = await registration(display_node=239, **{**evidence, "evidence_revision_sha256": "0" * 64})
            assert stale["error"]["code"] == "integrity_error"
            bad_frame = {"run_id": RUN, "display_node": 239, **fields, "evidence_frame": "gltf_world_m"}
            invalid = await client.call_tool("anatomy_lab", {"request": {"operation": "muscle.registration", **bad_frame}})
            assert invalid.is_error
            try:
                http(origin, "muscle.registration", bad_frame)
            except HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("mismatched evidence frame succeeded")
            print("PASS exact evidence over HTTP and stdio for 12 pilot surfaces, five states, and frame/revision negatives.")

    with (out / "registration-selections.json").open("w") as stream:
        json.dump({"groups": groups, "views": views, "open_selection": "pectoral"}, stream, indent=2, allow_nan=False)
    print("PASS five pinned selection cases and twelve revision, selector, side, group and paging controls.")


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1], Path(sys.argv[2])))
