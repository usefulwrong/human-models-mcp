"""Summarize the two crosswalks and verify the installed geometry inventory."""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

from glb import array, unpack
from anatomy_lab import digest

ROOT = Path(__file__).resolve().parents[2]
RUN = "14f5e412-a31e-4b72-b008-278bd8c96ce3"
V09 = ROOT / "outputs/v09"


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main(out):
    def write(name, data):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    before = read(out / "baseline-crosswalk.json")
    data = read(out / "MUSCLE_CROSSWALK_V2.json")
    original_pin = ROOT / "reports/v09_muscle_intelligence/ACTUATOR_CROSSWALK.json"
    run = V09 / "motion/run-01/results" / RUN
    manifest = read(run / "manifest.json")
    scene_path = V09 / "moving-human/clip-final/motion.json"
    scene = read(scene_path)
    upstream = V09 / "data/upstream"
    models = ROOT / "models/ms_human_700"
    assets = V09 / "composite-organs/install-clean"
    visual_inputs = ROOT / "outputs/v08/atlas-expansion"
    source_glb = visual_inputs / "sources/fullbody_atlas_light.glb"
    source_doc, source_blob = unpack(source_glb.read_bytes())
    prior_qa = ROOT / "reports/v09_muscle_intelligence/GEOMETRY_QA.json"
    source_controls = read(out / "scenes/source-integrity.json")
    assert data["source_result_sha256"] == before["source_result_sha256"] == sha(run / "manifest.json")
    assert sha(scene_path) == data["motion_sha256"] == before["motion_sha256"]
    assert len({r["tendon_id"] for r in data["rows"]}) == len(data["rows"]) == 700
    assert all(sha(run / name) == item["sha256"] for name, item in manifest["artifacts"].items())

    geom = defaultdict(list)
    for item in data["source_geometry_inventory"]["bodyparts3d"]:
        path = assets / "meshes" / item["filename"]
        status = "MISSING" if not path.is_file() else "MATCH" if (
            item["bytes"] == path.stat().st_size and item["sha256"] == sha(path)) else "MISMATCH"
        geom[status].append(item["fj_id"])
    for item in data["source_geometry_inventory"]["myosuite"]:
        prim, = source_doc["meshes"][source_doc["nodes"][item["source_node"]]["mesh"]]["primitives"]
        attrs = prim["attributes"]
        raw = b"".join(array(source_doc, source_blob, idx).tobytes()
                       for idx in (attrs["POSITION"], prim["indices"], attrs["JOINTS_0"], attrs["WEIGHTS_0"]))
        assert digest(raw) == item["source_mesh_sha256"], item["name"]
    pins = read(ROOT / "scripts/anatomy_lab/sources.lock.json")
    membership = {}
    for suffix in ("43", "43i"):
        name = f"original-FMA2Obj-{suffix}"
        record = pins[f"{name}.zip"]
        payload, zip_path = upstream / f"{name}.txt", upstream / f"{name}.zip"
        membership[name] = {"txt_sha256": sha(payload), "archive_sha256": sha(zip_path),
                            "pin": record["membership"], "url": record["url"]}
        assert membership[name]["txt_sha256"] == record["membership"]["sha256"]
    docker_images = subprocess.check_output(["docker", "images", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"],
                                           text=True).splitlines()
    write("BASELINE_ACTUAL.json", {
        "repository": {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                       "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
                       "initial_status": (out / "changes/git-status-before.txt").read_text(encoding="utf-8").splitlines(),
                       "source_state": "Pilot patch present in staged app. Working Anatomy Lab is patch input."},
        "host": {"python": sys.version, "packages": {name: version(name) for name in ("mujoco", "numpy", "mcp", "pydantic", "pytest")}},
        "docker_images": [r for r in docker_images if r.startswith(("hmm-", "mcr.microsoft.com/playwright:"))],
        "docker_environment_log": "logs/environment.log",
        "source_files": {str(path.relative_to(ROOT)): sha(path) for path in (
            ROOT / "models.lock.json", ROOT / "renderer.lock.json", ROOT / "visual_sources.json",
            ROOT / "scripts/anatomy_lab/sources.lock.json",
            *sorted((models / "assets/muscle").glob("*.xml")), *sorted((models / "assets/tendon").glob("*.xml")),
        )},
        "dataset_pins": {"myosuite_light": {"sha256": sha(source_glb), "revision": "afa8427188c8bd054925200c70db6757908dee45"},
                         "bodyparts3d_catalog_sha256": sha(assets / "catalog.json"),
                         "bodyparts3d_memberships": membership,
                         "z_anatomy_derived_source": scene["assets"],
                         "myo_sim": read(Path(__file__).with_name("SOURCE_ABBREVIATIONS.json"))["file_sha256"]},
        "run": {"id": RUN, "scenario": manifest["scenario_id"], "sample_count": len(scene["frames"]),
                "duration_s": scene["frames"][-1]["frame_time"], "control": scene["control"],
                "acceptance": scene["acceptance"], "source_model": manifest["model"],
                "manifest_sha256": sha(run / "manifest.json"), "trajectory_sha256": sha(run / "trajectory.npz"),
                "motion_sha256": sha(scene_path), "motion_glb_sha256": sha(scene_path.with_name("motion.glb")),
                "artifact_sha256": {name: item["sha256"] for name, item in source_controls["artifacts"].items()}},
        "native_count": len(data["rows"]), "tendon_count": len({r["tendon_id"] for r in data["rows"]}),
        "reproduced_pilot_counts": before["counts"],
        "comparison_to_previous": {"pilot_crosswalk_regenerated_sha256": sha(out / "baseline-crosswalk.json"),
                                   "prior_crosswalk_sha256": sha(original_pin),
                                   "counts_identical": before["counts"] == read(original_pin)["counts"],
                                   "previous_geometry_qa": {"sha256": sha(prior_qa), "status": "HISTORICAL"},
                                   "old_strict_tree_failed_links": 14,
                                   "same_run_used": True},
        "commands": ["logs/environment.log", "logs/baseline-crosswalk.log", "logs/native-source.log",
                     "logs/strict-before.log", "logs/coverage-audit.log"]})

    regions = {}
    for previous, row in zip(before["rows"], data["rows"], strict=True):
        assert (previous["id"], previous["exact_name"], previous["links"], previous["coarse_group"]) == (
            row["id"], row["exact_name"], row["links"], row["coarse_group"])
        region = regions.setdefault(row["region"], {"before": Counter(), "after": Counter(), "side": Counter(),
                                                  "pinned_label": 0, "linked_paths": 0})
        region["before"][previous["status"]] += 1
        region["after"][row["status"]] += 1
        region["side"][row["side"]] += 1
        region["pinned_label"] += bool(row["canonical"]["pinned_name_matches"])
        region["linked_paths"] += bool(row["display_assets"])
    sides = defaultdict(dict)
    for row in data["rows"]:
        if row["side"] != "unknown":
            sides[row["canonical"]["stem"]][row["side"]] = {
                "id": row["id"], "source_name": row["exact_name"], "status": row["status"],
                "fma_ids": [c["fma_id"] for c in row["concept_membership"]],
                "display_ids": row["display_assets"]}
    write("COVERAGE_BY_REGION.json", {"region": regions, "side_pairs": sides,
        "unspecified_side": sum(r["side"] == "unknown" for r in data["rows"]),
        "unpaired_stems": [k for k, v in sides.items() if len(v) != 2],
        "asymmetric_status_stems": [k for k, v in sides.items() if len(v) == 2
                                    and v["left"]["status"] != v["right"]["status"]],
        "source_inventory": {"bodyparts3d_verified_bytes": len(geom["MATCH"]),
                             "bodyparts3d_missing": geom["MISSING"], "bodyparts3d_mismatch": geom["MISMATCH"],
                             "bodyparts3d_relation": Counter(r["actuator_relation"] for r in data["source_geometry_inventory"]["bodyparts3d"]),
                             "myosuite_source_mesh_hashes_verified": len(data["source_geometry_inventory"]["myosuite"]),
                             "myosuite_display_status": Counter(r["mode"] for r in data["source_geometry_inventory"]["myosuite"]),
                             "z_anatomy_moving": len(data["source_geometry_inventory"]["z_anatomy"])},
        "reviewed_concepts": [{"id": r["id"], "exact_name": r["exact_name"], **c}
                              for r in data["rows"] for c in r["concept_membership"] if c["status"] == "REVIEWED_ANATOMICAL"],
        "geometry_with_reviewed_link": list(data["reviewed_display_assets"].values()),
        "geometry_only": [item for n, item in data["motion_display_assets"].items() if n not in data["reviewed_display_assets"]]})
    write("REVIEW_QUEUE.json", {"basis_sha256": sha(out / "MUSCLE_CROSSWALK_V2.json"),
        "full_authored_4_3i_inference_set": "NOT_VERIFIED",
        "items": [{k: r[k] for k in ("id", "exact_name", "region", "side", "status", "status_axes",
                                    "reason_codes", "canonical", "concept_membership")}
                  for r in data["rows"] if r["status_axes"]["anatomical_concept"] != "REVIEWED_ANATOMICAL"],
        "moving_asset_without_reviewed_path_ids": [n for n in data["motion_display_assets"]
                                                    if n not in data["reviewed_display_assets"]]})
    assert not (geom["MISSING"] or geom["MISMATCH"]), geom
    print(f"PASS {len(geom['MATCH'])} pinned BodyParts3D assets and all MyoSuite source geometry hashes")


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("out", type=Path)
    main(args.parse_args().out)
