"""Fingerprint the unchanged scientific run and compare the two geometry source domains."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from anatomy_lab import digest, read_bounded
from glb import array, unpack
from human_models_mcp.atlas import verify_asset


def check(args):
    manifest_raw = read_bounded(args.run / "manifest.json", 1 << 20)
    manifest = json.loads(manifest_raw)
    results = {}
    for name, record in manifest["artifacts"].items():
        path = args.run / name
        if not path.is_file():
            results[name] = {"status": "NOT_INSTALLED", "expected_sha256": record["sha256"]}
            continue
        with path.open("rb") as stream:
            actual = sha256(stream.read()).hexdigest()
        if actual != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError("scientific source content differs: " + name)
        results[name] = {"status": "PASS", **record}
    data = json.loads(args.crosswalk.read_bytes())
    raw = args.catalog.read_bytes()
    if digest(raw) != data["anatomy_revision"] or digest(manifest_raw) != data["source_result_sha256"]:
        raise ValueError("wrong scientific source pin")
    catalog = {x["fj_id"]: x for x in json.loads(raw)["meshes"]}
    source_doc, source_blob = unpack(args.myo.read_bytes())
    controls = []
    assets = data["reviewed_display_assets"].values()
    for a in assets:
        if not a["group_id"].startswith("pectoralis_major"):
            continue
        bp = catalog[a["fj_label"]]
        path = args.catalog.parent / "meshes" / bp["filename"]
        verify_asset(path, bp)
        obj = [line.split() for line in path.read_text().splitlines()]
        vertices = np.asarray([[float(v) for v in parts[1:]] for parts in obj if parts and parts[0] == "v"])
        triangles = [parts[1:] for parts in obj if parts and parts[0] == "f"]
        prim, = source_doc["meshes"][source_doc["nodes"][a["source_node"]]["mesh"]]["primitives"]
        source_points = array(source_doc, source_blob, prim["attributes"]["POSITION"])
        n_faces = array(source_doc, source_blob, prim["indices"]).size // 3
        controls.append({"label": a["name"], "fma_id": a["fma_id"], "bodyparts3d": {
            "id": bp["fj_id"], "sha256": bp["sha256"], "vertices": len(vertices), "faces": len(triangles),
            "raw_bounding_extent_mm": np.ptp(vertices, axis=0).tolist()},
            "myosuite": {"id": a["mesh_id"], "sha256": a["geometry_sha256"], "vertices": len(source_points),
                         "faces": n_faces, "raw_bounding_extent_m": np.ptp(source_points, axis=0).tolist()},
            "identical_topology": [len(vertices), len(triangles)] == [len(source_points), n_faces],
            "attachment_registration": "NOT_VERIFIED"})
    result = {"run_id": manifest["run_id"], "manifest_sha256": digest(manifest_raw), "artifacts": results,
              "acceptance": manifest["scientific"]["acceptance"], "bodyparts3d_control": controls,
              "method": "Actual pinned raw OBJ vs actual MyoSuite GLB. Extents use each source basis."}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Original artifact hashes", {s: sum(r["status"] == s for r in results.values())
                                       for s in ("PASS", "NOT_INSTALLED")}, "paired raw geometries", len(controls))


if __name__ == "__main__":
    options = argparse.ArgumentParser(description=__doc__)
    for name in ("crosswalk", "catalog", "myo", "run", "output"):
        options.add_argument("--" + name, type=Path, required=True)
    check(options.parse_args())
