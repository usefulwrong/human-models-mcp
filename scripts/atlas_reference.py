"""Verify and open the pinned MyoSuite reference atlas in headless Blender."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen

REVISION = "afa8427188c8bd054925200c70db6757908dee45"
ASSET_NAME = "fullbody_atlas_light.glb"
ASSET_URL = (
    "https://huggingface.co/datasets/myohub/myosuite-assets/resolve/"
    + REVISION + "/muscles/" + ASSET_NAME
)
ASSET_BYTES = 10_424_448
ASSET_SHA256 = "1d74b59bf052f568b558eb05a4508b06e9482f342e1fe01fae543471c53ca9a4"
LICENSE = "CC-BY-4.0"
ROOT = Path(__file__).resolve().parents[1]


def verify(path):
    if not path.is_file() or path.stat().st_size != ASSET_BYTES:
        raise ValueError("atlas byte length differs from the pin")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ASSET_SHA256:
            raise ValueError("atlas SHA-256 differs from the pin")


def fetch(path):
    with urlopen(ASSET_URL, timeout=60) as response:
        data = response.read(ASSET_BYTES + 1)
    if len(data) != ASSET_BYTES or hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise ValueError("downloaded atlas differs from the pin")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-license", required=True, choices=[LICENSE])
    parser.add_argument("--asset", type=Path, default=ROOT / "outputs/atlas-assets" / ASSET_NAME)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    args = parser.parse_args()
    asset = args.asset.resolve()
    destination = args.output.resolve()
    if destination.exists():
        parser.error("choose a new output directory")
    if not asset.exists() and not args.offline:
        fetch(asset)
    verify(asset)
    destination.mkdir(parents=True)
    gpu = ["--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics"] if args.device == "gpu" else []
    subprocess.run([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--cpus", "4", "--memory", "6g", "--pids-limit", "128",
        "--tmpfs", "/tmp:size=512m,mode=1777", "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "BLENDER_USER_CONFIG=/tmp/blender", "-e", "XDG_CACHE_HOME=/tmp/cache",
        "-e", "XDG_CONFIG_HOME=/tmp/config", "-e", "CUDA_CACHE_PATH=/tmp/cuda",
        "-v", f"{asset}:/atlas.glb:ro", "-v", f"{destination}:/atlas-output",
        "-v", f"{Path(__file__).with_name('atlas_reference_blender.py')}:/atlas_reference.py:ro",
        *gpu, "--entrypoint", "/opt/blender/blender",
        os.environ.get("HMM_RENDER_IMAGE", "human-models-mcp-night-renderer:local"),
        "-b", "--factory-startup", "--python-exit-code", "1", "--python", "/atlas_reference.py", "--",
        args.device, ASSET_URL, ASSET_SHA256,
    ], check=True, timeout=600)
    print(destination)


if __name__ == "__main__":
    main()
