"""Compare v0.7.1/v0.8 scientific outputs and audit the atlas SDK/CLI replays."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw


def read(path):
    return json.loads(path.read_text())


def numerical_regression(before, after):
    def runs(result):
        return [value["run"] for value in (result["knee"], result["forward"], *[
            run for group in ("v03", "v04", "v05") for run in result[group].values()
            if isinstance(run, dict) and "run" in run
        ])] + [result["run"]]

    cases = {}
    for transport in ("stdio", "http"):
        legacy = {r["scenario_id"]: r for r in runs(before[transport])}
        current = {r["scenario_id"]: r for r in runs(after[transport])}
        assert legacy.keys() == current.keys() and len(legacy) >= 9
        for scenario, original in legacy.items():
            actual = current[scenario]
            old_model, new_model = original["model"], actual["model"]
            assert {k: v for k, v in old_model.items() if k != "derivation"} == {
                k: v for k, v in new_model.items() if k != "derivation"}
            # Diagnostic MJCF XML embeds the E2E runner's random absolute asset root.
            assert {k: v for k, v in old_model.get("derivation", {}).items() if k != "derived_mjcf_sha256"} == {
                k: v for k, v in new_model.get("derivation", {}).items() if k != "derived_mjcf_sha256"}
            assert original["execution"]["parameters"] == actual["execution"]["parameters"]
            ref = original["outputs"]["metrics"]
            got = actual["outputs"]["metrics"]
            assert [(m["name"], m["unit"]) for m in ref] == [(m["name"], m["unit"]) for m in got]
            difference = max(abs(x["value"] - y["value"]) for x, y in zip(ref, got, strict=True))
            assert difference <= 1e-10
            cases[f"{transport}/{scenario}"] = difference
    return cases


def audit_atlas(cpu, gpu, run_store, contact_sheet):
    info = [read(p / "passport.json") for p in (cpu, gpu)]
    frame_lists = [read(p / "frames.json")["frames"] for p in (cpu, gpu)]
    run_id = info[0]["source_run_id"]
    assert info[1]["source_run_id"] == run_id
    assert info[0]["renderer"]["device"]["backend"] == "cpu"
    assert info[1]["renderer"]["device"]["backend"] in {"optix", "cuda"} and info[1]["fallback"] is None
    assert info[0]["source_files"] == info[1]["source_files"]
    for name, expected in info[0]["source_files"].items():
        assert hashlib.sha256((run_store / run_id / name).read_bytes()).hexdigest() == expected, name
    for directory, passport, frames in zip((cpu, gpu), info, frame_lists, strict=True):
        with ZipFile(directory / "source.zip") as archive:
            assert set(archive.namelist()) == passport["source_files"].keys()
            for name, expected in passport["source_files"].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        with ZipFile(directory / "frames.zip") as archive:
            for f in frames:
                data = archive.read(f"frame_{f['frame']:04d}.png")
                assert hashlib.sha256(data).hexdigest() == f["png_sha256"]
    physics_keys = ("source_index", "time_s", "state_sha256")
    assert [[tuple(f[k] for k in physics_keys) for f in frames] for frames in frame_lists][0] == [
        tuple(f[k] for k in physics_keys) for f in frame_lists[1]
    ]
    registration = read(cpu / "anatomy_registration.json")
    assert registration == read(gpu / "anatomy_registration.json")
    assert registration["status"] == "illustrative"
    assert registration["source"]["license"] == "CC-BY-SA-2.1-JP"
    assert registration["blender"]["status"] == "PASS"
    phases = registration["phase_source_indices"]
    assert phases["start"] < phases["bottom"] < phases["return"]
    assert any(f["max_vertex_motion_since_previous_sample_m"] > .01 for f in registration["frames"][1:])
    sheet = Image.new("RGB", (1440, 302), "#101923")
    labels = ImageDraw.Draw(sheet)
    with ZipFile(cpu / "frames.zip") as archive:
        for i, key in enumerate(("start", "bottom", "return")):
            f = next(f for f in frame_lists[0] if f["source_index"] == phases[key])
            panel = Image.open(io.BytesIO(archive.read(f"frame_{f['frame']:04d}.png"))).convert("RGB")
            panel.thumbnail((480, 270))
            sheet.paste(panel, (480 * i, 22))
            labels.text((480 * i + 8, 4), f"{key.upper()} | source {phases[key]}, {f['time_s']:.2f} s", fill="white")
    sheet.save(contact_sheet)
    return {"run_id": run_id, "phases": phases, "cpu": info[0]["renderer"]["device"],
            "gpu": info[1]["renderer"]["device"], "byte_identical_source_files": len(info[0]["source_files"]),
            "identical_registration": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--cpu", type=Path, required=True)
    parser.add_argument("--gpu", type=Path, required=True)
    parser.add_argument("--run-store", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path, required=True)
    args = parser.parse_args()
    result = {"numerical_differences": numerical_regression(read(args.before), read(args.after)),
              "atlas": audit_atlas(args.cpu, args.gpu, args.run_store, args.contact_sheet)}
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
