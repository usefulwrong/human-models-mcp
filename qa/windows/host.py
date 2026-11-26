"""Serve fixtures and collect named logs inside the isolated Windows QA container."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.ps1': 'text/plain; charset=utf-8'}

    def do_PUT(self):
        if not re.fullmatch(r"/[0-9a-f]{16}\.(log|json|png|zip)", self.path):
            self.send_error(400)
            return
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 8 * 1024**2:
            self.send_error(413)
            return
        Path(self.path[1:]).write_bytes(self.rfile.read(size))
        self.send_response(201)
        self.end_headers()

    def log_message(self, format, *args):
        if "/request.txt" not in (self.requestline or ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8788), Handler).serve_forever()
