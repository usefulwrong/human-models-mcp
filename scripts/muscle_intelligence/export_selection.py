"""Capture a published typed selection and its saved curves for the local Blender exporter."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters


async def capture(run_id, output):
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "lab_mcp"],
                                           env=dict(os.environ))) as client:

        async def query(operation, **fields):
            reply = await client.call_tool("anatomy_lab", {"request": {"operation": operation,
                                                                      "run_id": run_id, **fields}})
            data = reply.structured_content
            if reply.is_error or not data or data["status"] != "ok":
                raise ValueError(f"Unable to read {operation} for the installed run")
            return data

        receipt = await query("muscle.selection")
        selection = receipt["selection"]
        if not selection:
            raise ValueError("Publish an exact selection before export")
        groups, curves = {}, {}
        group = receipt["group"]
        actuator = selection["actuator_id"]
        if actuator is not None or group:
            selector = {"actuator_ids": [actuator]} if actuator is not None else {"group_id": group["group_id"]}
            property_name = selection["metric"]
            curves[property_name] = await query("muscle.timeseries", metric=property_name, **selector)
            if selection["overlay"] and "activation" not in curves:
                curves["activation"] = await query("muscle.timeseries", metric="activation", **selector)
            if any(curve["mapping_revision_sha256"] != receipt["mapping_revision_sha256"]
                   or curve["motion_sha256"] != receipt["motion_sha256"] for curve in curves.values()):
                raise ValueError("Selection and source curves changed during export")
        if selection["overlay"]:
            groups[group["group_id"]] = {"selection": receipt, "entries": curves}
        target = {"groups": groups, "views": {"selected": {**receipt, "curves": curves}}, "open_selection": "selected"}
        with output.open("x") as stream:
            json.dump(target, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("run_id")
    args.add_argument("output", type=Path)
    opts = args.parse_args()
    asyncio.run(capture(opts.run_id, opts.output))
