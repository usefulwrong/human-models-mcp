"""One real MCP request selected by an agent; preserves raw protocol receipts."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from mcp import Client, StdioServerParameters


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="tool name, or discover for the live tool schemas")
    parser.add_argument("--arguments", default="{}", help="JSON object, forwarded as MCP arguments")
    parser.add_argument(
        "--artifact-output", type=Path, help="decode a get_artifact response into this new local file"
    )
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        help="trusted project-local scenario directory for an authoring test; mounted read-only",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    command = [
        "compose",
        "-f",
        str(root / "compose.yaml"),
        "-p",
        os.environ.get("COMPOSE_PROJECT_NAME", "human-models-mcp-night"),
        "run",
        "--rm",
        "--no-deps",
        "-T",
    ]
    if args.scenario_dir:
        folder = args.scenario_dir.resolve()
        if not folder.is_relative_to(root) or not folder.is_dir():
            raise ValueError("scenario-dir must be an existing directory inside this project")
        command.extend(["-v", str(folder) + ":/app/scenarios:ro"])
    command.append("runtime")
    source = StdioServerParameters(
        command="docker",
        args=command,
        cwd=str(root),
        env={key: os.environ[key] for key in ("HMM_RESULTS_DIR", "HMM_RUNTIME_IMAGE", "HMM_RENDER_IMAGE", "COMPOSE_PROJECT_NAME", "HMM_UID", "HMM_GID") if key in os.environ},
    )
    arguments = json.loads(args.arguments)
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    async with Client(source, read_timeout_seconds=120) as client:
        if args.tool == "get_render_artifact" and args.artifact_output:
            from render_artifacts import download

            if arguments.get("offset", 0) != 0:
                raise ValueError("whole artifact output starts at offset zero")
            result = await download(
                client, arguments["job_id"], arguments["artifact_id"], args.artifact_output, args.trace_dir
            )
            print(json.dumps({"result": result}, indent=2))
            return
        if args.tool == "discover":
            result = {"tools": [item.model_dump(mode="json") for item in (await client.list_tools()).tools]}
        else:
            response = await client.call_tool(args.tool, arguments)
            if response.is_error or response.structured_content is None:
                raise RuntimeError(str(response.content))
            result = response.structured_content
        receipt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": args.tool,
            "arguments": arguments,
            "result": result,
            "protocol": str(client.protocol_version),
            "client": "official SDK; tool selection belongs to the calling LLM",
        }
        args.trace_dir.mkdir(parents=True, exist_ok=True)
        trace = args.trace_dir / (str(uuid4()) + ".json")
        trace.write_text(json.dumps(receipt, indent=2) + "\n")
        if args.artifact_output:
            if args.tool != "get_artifact" or result.get("status") != "ok":
                raise ValueError("artifact-output requires a successful get_artifact")
            data = (
                base64.b64decode(result["data"], validate=True)
                if result["encoding"] == "base64"
                else result["data"].encode()
            )
            if hashlib.sha256(data).hexdigest() != result["sha256"]:
                raise ValueError("artifact checksum mismatch")
            args.artifact_output.parent.mkdir(parents=True, exist_ok=True)
            with args.artifact_output.open("xb") as stream:
                stream.write(data)
            result = {k: v for k, v in result.items() if k != "data"}
            result["saved_to"] = str(args.artifact_output.resolve())
        print(json.dumps({"receipt": str(trace), "result": result}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
