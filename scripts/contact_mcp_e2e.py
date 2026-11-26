"""Exercise the experimental run through independent offline MCP transports."""

import asyncio
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

from mcp import Client, StdioServerParameters

from human_models_mcp.results import store


async def call(client, name, **params):
    result = await client.call_tool(name, params)
    assert not result.is_error, result
    return result.structured_content


async def query(client, run_id):
    result = await call(client, "get_result", run_id=run_id)
    assert result["scenario_id"] == "pushup_palms_contact"
    assert result["counts"]["actuators"] == 700 and result["counts"]["equality_constraints"] == 42
    assert result["scientific"]["acceptance"]["external_control"] == "USED"
    states = []
    for sample in (0, 5, 55, 110):
        parts = []
        for part in ("hand_l", "hand_r", "l_bofoot", "r_bofoot"):
            row = await call(client, "get_contact", run_id=run_id, part=part, sample=sample)
            by_time = await call(client, "get_contact", run_id=run_id, part=part, time_s=row["time_s"])
            assert row == by_time
            parts.append(row)
        states.append(parts)
    errors = {}
    for quantity in ("skin_contact_pressure", "ligament_load"):
        row = await call(client, "get_contact", run_id=run_id, part="hand_l", sample=0, quantity=quantity)
        assert row["status"] == "unsupported" and row["measurement_status"] == "UNSUPPORTED"
        errors[quantity] = row
    for label, params in (("unknown_part", {"part": "../../hand", "sample": 1}),
                          ("unknown_time", {"part": "hand_l", "time_s": .011}),
                          ("missing_clock", {"part": "hand_l"})):
        row = await call(client, "get_contact", run_id=run_id, **params)
        assert row["status"] == "invalid_input"
        errors[label] = row
    artifact = await call(client, "get_artifact", run_id=run_id, artifact_id="contact_manifest.json")
    assert artifact["sha256"] == hashlib.sha256(artifact["data"].encode()).hexdigest()
    index = await call(client, "get_artifact", run_id=run_id, artifact_id="contact_steps.json")
    chunk_name = json.loads(index["data"])["chunks"][0]
    chunk = await call(client, "get_artifact", run_id=run_id, artifact_id=chunk_name)
    assert chunk["mime_type"] == "application/gzip" and chunk["encoding"] == "base64"
    return {"protocol": str(client.protocol_version), "states": states, "errors": errors,
            "trajectory_sha256": result["artifacts"]["trajectory.npz"]["sha256"]}


async def main(output):
    with socket.socket() as sock:
        assert sock.connect_ex(("192.0.2.1", 443)) != 0
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "human_models_mcp"]),
                      read_timeout_seconds=120) as sdk:
        invalid = await call(sdk, "run_scenario", scenario_id="pushup_palms_contact", parameters={"support_boundary": "fixed_points"})
        assert invalid["status"] == "invalid_input", invalid
        run = await call(sdk, "run_scenario", scenario_id="pushup_palms_contact", idempotency_key="contact-integrity-offline-v1")
        assert run["status"] == "computed", run
        run_id = run["run_id"]
        same = await call(sdk, "run_scenario", scenario_id="pushup_palms_contact", idempotency_key="contact-integrity-offline-v1")
        assert same["run_id"] == run_id
        stdio = await query(sdk, run_id)
    with subprocess.Popen([sys.executable, "-m", "human_models_mcp", "--transport", "http"]) as http:
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", 8765), timeout=.1):
                        break
                except OSError:
                    await asyncio.sleep(.05)
            async with Client("http://127.0.0.1:8765/mcp", read_timeout_seconds=120) as sdk:
                over_http = await query(sdk, run_id)
        finally:
            http.terminate()
    assert stdio == over_http
    manifest_sha = hashlib.sha256((store() / run_id / "manifest.json").read_bytes()).hexdigest()
    (output / "mcp-transcript.json").write_text(json.dumps({
        "run_id": run_id, "manifest_sha256": manifest_sha, "sdk_transports": ["stdio", "streamable-http"],
        "invalid_scenario_parameters": invalid, "stdio": stdio, "http": over_http}, indent=2) + "\n")
    (output / "fresh-id").write_text(run_id + "\n")
    print(run_id, manifest_sha, stdio["trajectory_sha256"])


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
