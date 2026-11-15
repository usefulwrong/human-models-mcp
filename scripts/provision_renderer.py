"""Download the reviewed official Blender archive; no remote installation scripts."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--atlas-reference",
        action="store_true",
        help="cache the reviewed HRA reference only; does not enable registration/rendering",
    )
    args = parser.parse_args()
    item = json.loads((ROOT / "renderer.lock.json").read_text())["blender"]
    path = ROOT / "render_vendor" / item["url"].rsplit("/", 1)[-1]
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(".part")
        with urllib.request.urlopen(item["url"], timeout=120) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
        temporary.replace(path)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
            raise RuntimeError("Blender archive hash mismatch; retained for inspection")
    print("Official Blender archive verified:", path.name)
    if args.atlas_reference:
        registry = json.loads((ROOT / "visual_sources.json").read_text())
        reference = next(x for x in registry["sources"] if x["id"] == "hra_knee_female_left_v1_3")
        folder = ROOT / "render_vendor/reference"
        folder.mkdir(exist_ok=True)
        for name, file in reference["files"].items():
            target = folder / name
            if not target.exists():
                with urllib.request.urlopen(file["url"], timeout=60) as stream:
                    data = stream.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError("reference exceeds reviewed size bound")
                target.write_bytes(data)
            if (
                target.stat().st_size != file["bytes"]
                or hashlib.sha256(target.read_bytes()).hexdigest() != file["sha256"]
            ):
                raise ValueError("reference asset hash/size mismatch: " + name)
        print("HRA knee reference verified; registration remains unverified and layer disabled")


if __name__ == "__main__":
    main()
