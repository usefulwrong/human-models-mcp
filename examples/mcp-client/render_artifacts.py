"""Download bounded render chunks with the official MCP client; no server imports."""

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4


async def download(client, job_id, artifact_id, destination, trace_dir=None):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("choose a new artifact output file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + "." + str(uuid4()))
    offset = 0
    whole = hashlib.sha256()
    chunks = 0
    meta = None
    try:
        with temporary.open("xb") as stream:
            while True:
                arguments = {"job_id": job_id, "artifact_id": artifact_id, "offset": offset, "length": 262144}
                response = await client.call_tool("get_render_artifact", arguments)
                result = response.structured_content
                if response.is_error or not result or result.get("status") != "ok":
                    raise RuntimeError(str(response.content))
                if trace_dir:
                    folder = Path(trace_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / (str(uuid4()) + ".json")).write_text(
                        json.dumps(
                            {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "tool": "get_render_artifact",
                                "arguments": arguments,
                                "result": result,
                                "protocol": str(client.protocol_version),
                                "client": "official SDK; bounded chunk download selected by caller",
                            },
                            indent=2,
                        )
                        + "\n"
                    , encoding="utf-8", newline="\n")
                if not 0 <= result["bytes"] <= 128 * 1024 * 1024:
                    raise ValueError("artifact exceeds client bound")
                if meta is not None and (meta["sha256"], meta["bytes"]) != (
                    result["sha256"],
                    result["bytes"],
                ):
                    raise ValueError("artifact changed during transfer")
                meta = result
                chunk = base64.b64decode(result["data"], validate=True)
                if len(chunk) > 262144 or hashlib.sha256(chunk).hexdigest() != result["chunk_sha256"]:
                    raise ValueError("chunk hash/length mismatch")
                if result["offset"] != offset or result["next_offset"] != offset + len(chunk):
                    raise ValueError("chunk offset mismatch")
                whole.update(chunk)
                stream.write(chunk)
                offset += len(chunk)
                chunks += 1
                if result["eof"]:
                    break
                if not chunk:
                    raise ValueError("empty nonterminal chunk")
        if offset != meta["bytes"] or whole.hexdigest() != meta["sha256"]:
            raise ValueError("whole artifact hash/length mismatch")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        k: v for k, v in meta.items() if k not in ("data", "offset", "next_offset", "eof", "chunk_sha256")
    } | {"chunks": chunks, "saved_to": str(destination), "verified_sha256": whole.hexdigest()}
