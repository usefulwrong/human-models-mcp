"""Fetch only explicitly locked official model assets, with SHA-256 verification."""

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def provision(destination, *, cache=None, offline=False):
    lock = json.loads((ROOT / "models.lock.json").read_text(encoding="utf-8"))
    expected_base = "https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/" + lock["revision"] + "/"
    if lock["download_base"] != expected_base:
        raise ValueError("unexpected download source")

    def valid(path, item):
        return (path.is_file() and not path.is_symlink() and path.stat().st_size == item["size"]
                and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"])

    def fetch(item):
        rel = PurePosixPath(item["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] != "ms_human_700":
            raise ValueError("unsafe locked path")
        path = destination / rel
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise ValueError("linked model asset or directory")
        cached = cache / rel if cache is not None else path
        exists = valid(path, item)
        if exists and (cached == path or valid(cached, item)):
            return 0
        if cached != path and valid(cached, item):
            data = cached.read_bytes()
        elif exists:
            data = path.read_bytes()
        else:
            if offline:
                raise ValueError(f"missing or damaged offline model: {rel}")
            for retry in range(3):
                try:
                    with urllib.request.urlopen(expected_base + item["path"], timeout=45) as response:
                        data = response.read(item["size"] + 1)
                    break
                except OSError:
                    if retry == 2:
                        raise
                    time.sleep(retry + 1)
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"hash/size mismatch: {rel}")
        for target in {cached, path}:
            if any(p.is_symlink() or p.is_junction() for p in (target, *target.parents)):
                raise ValueError(f"linked file or directory: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.{uuid4().hex}.part")
            try:
                temp.write_bytes(data)
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
        return 1

    if shutil.disk_usage(destination.parent).free < sum(x["size"] for x in lock["files"]):
        raise OSError("insufficient space for the pinned model inventory")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = sum(pool.map(fetch, lock["files"]))
    print(json.dumps({"status": "verified", "files": len(lock["files"]), "updated": downloaded,
                      "revision": lock["revision"], "asset_sha256": lock["asset_sha256"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    provision(ROOT / "models", cache=args.cache, offline=args.offline)


if __name__ == "__main__":
    main()
