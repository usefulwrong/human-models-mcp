"""Fetch only explicitly locked official model assets, with SHA-256 verification."""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / "models.lock.json").read_text())
    expected_base = "https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/" + lock["revision"] + "/"
    if lock["download_base"] != expected_base:
        raise ValueError("unexpected download source")

    def fetch(item):
        rel = Path(item["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] != "ms_human_700":
            raise ValueError("unsafe locked path")
        path = ROOT / "models" / rel
        if path.is_symlink():
            raise ValueError("symlinked model asset")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
            return 0
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
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".download")
        temp.write_bytes(data)
        temp.replace(path)
        return 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = sum(pool.map(fetch, lock["files"]))
    print(json.dumps({"status": "verified", "files": len(lock["files"]), "downloaded": downloaded,
                      "revision": lock["revision"], "asset_sha256": lock["asset_sha256"]}))


if __name__ == "__main__":
    main()
