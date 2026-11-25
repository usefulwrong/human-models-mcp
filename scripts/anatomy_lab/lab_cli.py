"""Read one typed Anatomy Lab request from stdin and write JSON to stdout."""

import sys

from anatomy_lab import REQUEST, canonical
from lab_mcp import registry


if __name__ == "__main__":
    request = REQUEST.validate_json(sys.stdin.buffer.read(65537))
    sys.stdout.buffer.write(canonical(registry().call(request)) + b"\n")
