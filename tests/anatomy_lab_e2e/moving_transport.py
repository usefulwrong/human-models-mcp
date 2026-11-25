"""Compare canonical HTTP and fresh official stdio MCP replies plus actual artifact bytes."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

from mcp import Client, StdioServerParameters
from transports import canonical, exchange


async def main(origin, output):
    evidence = {}
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "lab_mcp"],
                                           env=dict(os.environ)), read_timeout_seconds=75) as client:
        async def compare(op, name=None, expected="ok", **fields):
            request = {"operation": op, **fields}
            mcp_reply = await client.call_tool("anatomy_lab", {"request": request})
            assert not mcp_reply.is_error, mcp_reply.content
            status, http_reply = exchange(origin, request)
            assert status == 200 and canonical(mcp_reply.structured_content) == canonical(http_reply)
            assert http_reply["status"] == expected, http_reply
            evidence[name or op] = {"request": request, "response_sha256": hashlib.sha256(canonical(http_reply)).hexdigest(),
                                    "status": expected, "transport_exact": True}
            return http_reply

        discovered = await compare("whole.discover")
        run, = discovered["runs"]
        run_id = run["run_id"]
        opened = await compare("whole.open", run_id=run_id)
        motion = opened["motion"]
        source = await client.call_tool("get_result", {"run_id": run_id, "claim_id": "gate:muscle_driven"})
        assert not source.is_error, source.content
        native = source.structured_content
        assert native["acceptance"]["muscle_driven"] == motion["acceptance"]["muscle_driven"] == "NOT_ACHIEVED"
        assert native["control_mode"] == motion["control"] == "assisted_muscle"
        evidence["recorded_gate"] = {"control": native["control_mode"], "result": native["claims"]}
        saved = json.loads((output / "saved-view.json").read_text())
        set_view = await compare("whole.set_view", run_id=run_id, view=saved)
        assert set_view["view"] == saved and len(motion["frames"]) == 111
        await compare("whole.set_view", "invalid_frame", expected="integrity_error", run_id=run_id,
                      view={**saved, "state_index": 400})
        await compare("whole.set_view", "wrong_motion_digest", expected="integrity_error", run_id=run_id,
                      view={**saved, "motion_sha256": "0" * 64})
        await compare("whole.set_view", "moving_skin_unavailable", expected="integrity_error", run_id=run_id,
                      view={**saved, "layers": ["SKIN"]})
        await compare("whole.open", "unknown_run", expected="unsupported",
                      run_id="12345678-1234-1234-1234-123456789012")
        for name in ("motion.glb", "coverage.json", "scene.blend", "assisted-pushup.mp4"):
            expected = "ok" if name in motion["artifacts"] or os.environ.get("HMM_LAB_WHOLE_RENDER_SHA") else "unsupported"
            result = await compare("whole.artifact", name, expected=expected, run_id=run_id, artifact_id=name)
            if expected == "ok":
                with urlopen(origin + result["url"], timeout=75) as stream:
                    data = stream.read(result["bytes"] + 1)
                    assert len(data) == result["bytes"] and hashlib.sha256(data).hexdigest() == result["sha256"]
                evidence[name]["verified_bytes"] = len(data)
                evidence[name]["artifact_sha256"] = result["sha256"]
        invalid = origin + "/api/whole/motion.glb/" + "0" * 64
        try:
            urlopen(invalid, timeout=5)
        except HTTPError as exc:
            assert exc.code == 404
            evidence["wrong_route_digest"] = {"http": exc.code}
        else:
            raise AssertionError("incorrect digest route served an asset")
    (output / "mcp-http.json").write_bytes(canonical(evidence) + b"\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
