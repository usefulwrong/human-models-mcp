import argparse
import os

from . import __version__
from .runtime.graphics import requested_backend


def main():
    parser = argparse.ArgumentParser(description="UsefulWrong local research MCP server")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    args = parser.parse_args()
    os.environ.setdefault("MUJOCO_GL", requested_backend())
    from .server import mcp
    if args.transport == "stdio":
        mcp.run()
    else:
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.run(transport="streamable-http", host="127.0.0.1", port=8765,
                stateless_http=True, json_response=True, max_request_body_size=65536,
                transport_security=TransportSecuritySettings(
                    allowed_hosts=["127.0.0.1:8765", "localhost:8765"], allowed_origins=[]))


if __name__ == "__main__":
    main()
