"""Verify and open the pinned MyoSuite reference atlas in headless Blender."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen

REVISION = "afa8427188c8bd054925200c70db6757908dee45"
ASSET_BASE_URL = "https://huggingface.co/datasets/myohub/myosuite-assets/resolve/" + REVISION + "/muscles/"
ASSETS = {
    "light": ("fullbody_atlas_light.glb", 10_424_448,
              "1d74b59bf052f568b558eb05a4508b06e9482f342e1fe01fae543471c53ca9a4"),
    "hd": ("fullbody_atlas.glb", 26_784_568,
           "11303157ba7bae54a865c58966e7e0a45b0dc07dccb7ca323a1b2f4a5748068b"),
}
LICENSE = "CC-BY-4.0"
ROOT = Path(__file__).resolve().parents[1]


def verify(path, quality="light"):
    _, size, digest = ASSETS[quality]
    if not path.is_file() or path.stat().st_size != size:
        raise ValueError("atlas byte length differs from the pin")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("atlas SHA-256 differs from the pin")


def fetch(path, quality="light"):
    name, size, digest = ASSETS[quality]
    with urlopen(ASSET_BASE_URL + name, timeout=60) as response:
        data = response.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("downloaded atlas differs from the pin")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-license", required=True, choices=[LICENSE])
    parser.add_argument("--asset", type=Path)
    parser.add_argument("--mesh-quality", choices=ASSETS, default="light")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    args = parser.parse_args()
    name, _, digest = ASSETS[args.mesh_quality]
    asset = (args.asset or ROOT / "outputs/atlas-assets" / name).resolve()
    destination = args.output.resolve()
    if destination.exists():
        parser.error("choose a new output directory")
    if not asset.exists() and not args.offline:
        fetch(asset, args.mesh_quality)
    verify(asset, args.mesh_quality)
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
        "-v", f"{ROOT / 'src/human_models_mcp/muscle_materials.py'}:/muscle-materials.py:ro",
        *gpu, "--entrypoint", "/opt/blender/blender",
        os.environ.get("HMM_RENDER_IMAGE", "human-models-mcp-night-renderer:local"),
        "-b", "--factory-startup", "--python-exit-code", "1", "--python", "/atlas_reference.py", "--",
        args.device, ASSET_BASE_URL + name, digest,
    ], check=True, timeout=600)
    print(destination)


if __name__ == "__main__":
    main()
