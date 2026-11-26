"""Stage the existing Muscle Intelligence integration in a fresh Anatomy Lab copy."""

import argparse
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PATCH_FILES = {
    "anatomy_lab.py", "moving_transport.py", "lab_mcp.py",
    "site/viewer.js", "site/whole_motion.js", "site/index.html", "site/style.css",
}


def apply_integration(lab):
    patch = (HERE / "anatomy_lab.patch").read_text(encoding="utf-8")
    for section in patch.split("\n--- a/"):
        lines = section.removeprefix("--- a/").splitlines(keepends=True)
        name = lines[0].strip()
        if name not in PATCH_FILES or lines[1].strip() != f"+++ b/{name}":
            raise ValueError(f"unexpected staged integration file: {name}")
        target = lab / name
        text = target.read_text(encoding="utf-8")
        for hunk in "".join(lines[2:]).split("\n@@ "):
            header, *changes = hunk.removeprefix("@@ ").splitlines(keepends=True)
            if " @@" not in header:
                raise ValueError(f"missing integration hunk header: {name}")
            # The separator consumes the preceding source line's newline.
            changes[-1] = changes[-1].rstrip("\n") + "\n"
            old = "".join(line[1:] for line in changes if line.startswith((" ", "-")))
            new = "".join(line[1:] for line in changes if line.startswith((" ", "+")))
            if not old or text.count(old) != 1:
                raise ValueError(f"staged integration context differs: {name}: {header.strip()}")
            text = text.replace(old, new, 1)
        target.write_text(text, encoding="utf-8", newline="\n")


def stage(target, assets):
    if target.exists() or target.is_symlink() or target.is_junction():
        raise FileExistsError(f"staged application destination must be new: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".muscles-", dir=target.parent) as directory:
        app = Path(directory) / "app"
        lab = app / "lab"
        shutil.copytree(ROOT / "scripts/anatomy_lab", lab, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        apply_integration(lab)
        for name in ("muscle_contract.py", "muscle_data.py", "registration_evidence.py"):
            shutil.copyfile(HERE / name, lab / name)
        site = lab / "site"
        for name in ("muscle_panel.js", "registration_panel.js", "landmark_editor.js", "landmark_editor.css"):
            shutil.copyfile(HERE / name, site / name)
        if (meshes := target.parent / "landmark-mesh").is_dir():
            shutil.copytree(meshes, site / "landmark-mesh")
        shutil.copytree(assets / "npm/node_modules", site / "npm/node_modules")
        shutil.copytree(assets / "full", site / "full")
        app.rename(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--assets", type=Path, default=ROOT / "outputs/v09/moving-human/site")
    args = parser.parse_args()
    stage(args.target, args.assets)
