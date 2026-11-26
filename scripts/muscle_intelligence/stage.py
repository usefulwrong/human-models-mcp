"""Apply the integration to a fresh local copy of the operator's Anatomy Lab."""

import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def stage(target, assets):
    target.mkdir()
    source = ROOT / "scripts/anatomy_lab"
    shutil.copytree(source, target / "lab", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    subprocess.run(["patch", "--batch", "--forward", "--no-backup-if-mismatch", "--fuzz=0",
                    "-p1", "-i", str(HERE / "anatomy_lab.patch")],
                   cwd=target / "lab", check=True)
    for name in ("muscle_contract.py", "muscle_data.py", "registration_evidence.py"):
        shutil.copyfile(HERE / name, target / "lab" / name)
    site = target / "lab/site"
    for name in ("muscle_panel.js", "registration_panel.js", "landmark_editor.js", "landmark_editor.css"):
        shutil.copyfile(HERE / name, site / name)
    if (meshes := target.parent / "landmark-mesh").is_dir():
        shutil.copytree(meshes, site / "landmark-mesh")
    shutil.copytree(assets / "npm/node_modules", site / "npm/node_modules")
    # Format v2 fetches asset packs through the server's pinned allowlist.
    shutil.copytree(assets / "full", site / "full")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--assets", type=Path, default=ROOT / "outputs/v09/moving-human/site")
    args = parser.parse_args()
    stage(args.target, args.assets)
