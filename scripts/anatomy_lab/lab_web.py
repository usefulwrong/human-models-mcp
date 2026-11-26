"""Static viewer and typed Anatomy Lab HTTP endpoint for loopback or a private LAN."""

import argparse
from contextlib import ExitStack
import json
import os
import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from anatomy_lab import REQUEST, SceneRequest, canonical, digest, read_bounded
from lab_mcp import registry
from human_models_mcp.results import error
from human_models_mcp.runtime.paths import flat_name, is_link


class LabHandler(SimpleHTTPRequestHandler):
    def trusted_host(self):
        address, port = self.server.server_address
        host = self.headers.get("Host")
        if self.server.lan is None:
            return host in {f"localhost:{port}", f"{address}:{port}"}
        return host == f"{address}:{port}" and IPv4Address(self.client_address[0]) in self.server.lan.network

    def end_headers(self):
        if self.command in {"GET", "HEAD"}:
            self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def safe_static_path(self):
        path = unquote(urlsplit(self.path).path)
        if (not path.startswith("/") or "\\" in path or "\x00" in path
                or any(not flat_name(part) for part in path.split("/") if part)):
            return False
        base = Path(self.directory).resolve()
        target = base / path.lstrip("/")
        try:
            if any(is_link(p) for p in (target, *target.parents) if p.is_relative_to(base)):
                return False
            return target.resolve().is_relative_to(base) and (
                not target.is_dir() or all((target / name).resolve().is_relative_to(base)
                                           for name in ("index.html", "index.htm")))
        except (OSError, RuntimeError):
            return False

    def do_GET(self):
        if not self.trusted_host():
            self.send_error(403)
            return
        if not self.safe_static_path():
            self.send_error(404)
            return
        if self.server.static_only:
            return super().do_GET()
        url = urlsplit(self.path)
        if url.path.startswith("/api/whole/"):
            try:
                name, expected = url.path.removeprefix("/api/whole/").split("/")
                if self.server.registry.whole is None:
                    raise LookupError("whole-body motion unavailable")
                with ExitStack() as opened:
                    stream, metadata = opened.enter_context(self.server.registry.whole.open_artifact(name))
                    if expected != metadata["sha256"]:
                        raise ValueError("incorrect artifact identity")
                    self.send_response(200)
                    self.send_header("Content-Type", self.guess_type(name))
                    self.send_header("Content-Length", str(metadata["bytes"]))
                    self.send_header("X-HMM-SHA256", metadata["sha256"])
                    self.end_headers()
                    try:
                        shutil.copyfileobj(stream, self.wfile)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            except (LookupError, OSError, ValueError):
                self.send_error(404, "Verified motion artifact unavailable")
            return
        if url.path.startswith("/api/pack/"):
            try:
                name, sha256 = url.path.removeprefix("/api/pack/").split("/")
                data = self.server.registry.pack_bytes(name, sha256)
            except (LookupError, OSError, ValueError):
                self.send_error(404, "Verified display pack unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.server.lan is not None and self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/?data=full")
            self.end_headers()
            return
        super().do_GET()

    def do_HEAD(self):
        if not self.trusted_host() or not self.safe_static_path():
            self.send_error(403)
            return
        super().do_HEAD()

    def do_POST(self):
        if not self.trusted_host() or self.headers.get("Origin") not in {
            None, "http://" + self.headers.get("Host", "")
        }:
            self.send_error(403)
            return
        if self.server.static_only:
            self.send_error(405)
            return
        if self.path not in {"/api/query", "/api/motion"} or self.headers.get_content_type() != "application/json":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 1 <= size <= 65536:
                raise ValueError("request size exceeds lab limits")
            request = REQUEST.validate_json(self.rfile.read(size))
        except (ValidationError, ValueError):
            self.reply(400, error("invalid_input", "invalid typed request"))
            return
        result = self.server.registry.call(request)
        if self.path == "/api/motion" and result["status"] == "ok":
            if not isinstance(request, SceneRequest) or request.operation != "scene.export" or not request.scene.motion:
                self.reply(400, error("invalid_input", "a motion scene document is required"))
                return
            data = read_bounded(self.server.registry.motion_path, 4 * 1024 * 1024)
            if digest(data) != request.scene.motion.motion_sha256:
                self.reply(409, error("integrity_error", "motion artifact changed during the request"))
                return
            result = {"status": "ok", "motion": json.loads(data)}
        self.reply(200, result)

    def reply(self, status, result):
        data = canonical(result)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--site", type=Path, default=Path(os.environ.get("HMM_LAB_SITE", "site")))
    parser.add_argument("--lan", type=IPv4Interface, metavar="ADDRESS/PREFIX")
    parser.add_argument("--static-only", action="store_true", help="Serve a staged report without loading the Registry")
    args = parser.parse_args()
    if not (args.site / "index.html").is_file():
        parser.error("site must contain index.html")
    if args.lan and (not args.lan.network.is_private or args.lan.ip.is_loopback
                     or args.lan.ip.is_link_local or args.lan.ip.is_unspecified):
        parser.error("LAN address and subnet must be within a private IPv4 range")
    address = str(args.lan.ip) if args.lan else "127.0.0.1"
    with ThreadingHTTPServer((address, args.port),
                             lambda *a: LabHandler(*a, directory=args.site)) as server:
        server.lan = args.lan
        server.static_only = args.static_only
        if not args.static_only:
            server.registry = registry(args.site)
        print(f"Listening on http://{address}:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
