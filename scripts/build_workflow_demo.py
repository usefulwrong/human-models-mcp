"""Package verified four-view MCP downloads for the public README."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw, ImageFont

VIEWS = {
    "simulation": ("pushup_scientific", "Simulation"),
    "muscle": ("pushup_muscle_paths", "Muscle Activity"),
    "anatomy": ("pushup_rectus", "Anatomy"),
    "cinematic": ("pushup_cinematic", "Cinematic"),
}
PHASES = ("start", "bottom", "return")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("download", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    target = args.output
    target.mkdir()
    records = {}
    clocks = []
    frames = Image.new("RGB", (1000, 895), "#111923")
    label = ImageDraw.Draw(frames)
    title = ImageFont.load_default(size=21)
    detail = ImageFont.load_default(size=15)
    for col, phase in enumerate(PHASES):
        label.text((16 + col * 326, 12), phase.upper(), font=detail, fill="#e9ae68")
    for row, (mode, (recipe, caption)) in enumerate(VIEWS.items()):
        source = args.download / recipe
        receipt = json.loads((source / "client.json").read_text())
        job = receipt["job"]
        clock = json.loads((source / "frames.json").read_text())
        clocks.append(clock)
        if clock["source_run_id"] != clocks[0]["source_run_id"] or any(
            [a[key] for a in clock["frames"]] != [b[key] for b in clocks[0]["frames"]]
            for key in ("source_index", "time_s", "state_sha256")
        ) or clock["phase_source_indices"] != clocks[0]["phase_source_indices"]:
            raise ValueError("demo views must share the same saved states and phases")

        selected = {**{f"{phase}.png": f"{mode}.png" if phase == "bottom" else None for phase in PHASES},
                    "animation.mp4": f"{mode}.mp4"}
        if mode == "muscle":
            selected.update({"animation.gif": "muscle.gif", "plot.png": "plot.png"})
        if mode == "anatomy":
            selected.update({name: name for name in ("anatomy_registration.json", "evidence.json", "passport.json", "frames.json")})
            archive = source / "source.zip"
            if digest(archive) != job["artifacts"]["source.zip"]["sha256"]:
                raise ValueError("downloaded source archive differs from job")
            with zipfile.ZipFile(archive) as saved:
                for name, destination in (("manifest.json", "scientific_manifest.json"),
                                          ("series.csv", "series.csv"), ("pectorals.csv", "pectorals.csv")):
                    data = saved.read(name)
                    if hashlib.sha256(data).hexdigest() != job["source_files"][name]:
                        raise ValueError("archived measurement differs from source: " + name)
                    (target / destination).write_bytes(data)
        records[mode] = {"recipe": recipe, "job_id": job["job_id"], "request": job["request"],
                         "backend": job["render_backend"]["backend"]}
        for name, destination in selected.items():
            path = source / name
            if digest(path) != job["artifacts"][name]["sha256"]:
                raise ValueError("download digest differs from job: " + name)
            if destination:
                shutil.copyfile(path, target / destination)
        y = 44 + row * 211
        label.text((16, y), caption, font=title, fill="#e5ebf2")
        for col, phase in enumerate(PHASES):
            with Image.open(source / (phase + ".png")) as panel:
                panel.thumbnail((316, 178), Image.Resampling.LANCZOS)
                frames.paste(panel, (16 + col * 326, y + 28))
    frames.save(target / "phases.png", optimize=True)
    metadata = {"source_run_id": clocks[0]["source_run_id"], "views": records,
                "phase_source_indices": clocks[0]["phase_source_indices"], "files": {
                    path.name: {"bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(target.iterdir())
                }}
    (target / "assets.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
