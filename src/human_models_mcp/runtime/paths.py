"""Portable identifiers and atomic publication of local records."""

import mimetypes
import os
from pathlib import PureWindowsPath
import stat
import time


def flat_name(name):
    return (isinstance(name, str) and bool(name) and name not in {".", ".."}
            and not name.endswith((".", " "))
            and not any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
            and not PureWindowsPath(name).is_reserved())


def is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def replace(source, destination):
    # Windows readers can temporarily hold an open handle without delete sharing.
    for attempt in range(21):
        try:
            source.replace(destination)
            return
        except PermissionError as exc:
            if os.name != "nt" or exc.winerror not in {5, 32} or attempt == 20:
                raise
            time.sleep(0.025)


def artifact_mime(path):
    fixed = {".csv": "text/csv", ".json": "application/json", ".txt": "text/plain", ".gz": "application/gzip"}
    return fixed.get(path.suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
