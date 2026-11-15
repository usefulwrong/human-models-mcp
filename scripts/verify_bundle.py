"""Verify a bundle using stdlib only; optionally load its project image."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def verify(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / "bundle.json").read_text())
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image_id"]):
        raise ValueError("invalid image digest")
    if manifest.get("renderer_image_id") and not re.fullmatch(
        r"sha256:[0-9a-f]{64}", manifest["renderer_image_id"]
    ):
        raise ValueError("invalid renderer image digest")
    if not manifest["image_tag"].startswith("human-models-mcp-night-"):
        raise ValueError("bundle must contain a project image")
    for name, digest in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            raise ValueError("unsafe or missing bundle file: " + name)
        actual = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        if actual != digest:
            raise ValueError("bundle SHA-256 mismatch: " + name)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--load", action="store_true", help="load the verified project Docker image")
    args = parser.parse_args()
    manifest = verify(args.directory)
    if args.load:
        for name in ("results", "reports", "render_jobs"):
            (args.directory.resolve() / name).mkdir(exist_ok=True)
        subprocess.run(["docker", "load", "-i", str(args.directory.resolve() / "image.tar")], check=True)
        actual = subprocess.check_output(
            ["docker", "image", "inspect", manifest["image_tag"], "--format", "{{.Id}}"], text=True
        ).strip()
        if actual != manifest["image_id"]:
            raise ValueError("loaded image ID differs from the recorded image")
    if args.load and manifest.get("renderer_image_id"):
        actual = subprocess.check_output(
            ["docker", "image", "inspect", manifest["renderer_image_tag"], "--format", "{{.Id}}"], text=True
        ).strip()
        if actual != manifest["renderer_image_id"]:
            raise ValueError("loaded renderer image differs")
    print(
        json.dumps(
            {
                "status": "verified",
                "image_id": manifest["image_id"],
                "files": len(manifest["files"]),
                "loaded": args.load,
            }
        )
    )


if __name__ == "__main__":
    main()
