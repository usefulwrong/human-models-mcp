"""Check installed asset bytes and trace a few independently selected FJ identifiers."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from anatomy_lab import Registry, REQUEST


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", type=Path)
    args = parser.parse_args()
    catalog = args.install / "catalog.json"
    meshes = args.install / "meshes"
    atlas = Registry(catalog, meshes)
    unique = {}
    for stem, filename in (("catalog", catalog), ("pack_manifest", atlas.pack_dir / "manifest.json")):
        unique[stem] = sha(filename)
    _, _, _, packs = atlas.display
    for name, info in packs.items():
        assert sha(atlas.pack_dir / name) == info["sha256"], name
    for row in atlas.catalog["meshes"]:
        assert sha(meshes / row["filename"]) == row["sha256"], row["fj_id"]

    samples = []
    rep = {"dataset": "BodyParts3D", "mesh_version": "4.3", "membership_version": "4.3+4.3i"}
    for concept, fj in (("FMA7088", "FJ2417"), ("FMA7309", "FJ6043"), ("FMA7310", "FJ3028"),
                        ("FMA7309", "FJ3028"), ("FMA50801", "FJ1732")):
        request = REQUEST.validate_python({"operation": "anatomy.resolve", "concept": concept,
                                           "representation": rep})
        members, _, _ = atlas.composite(concept, request.representation)
        member = next(m for m in members if m["fj_id"] == fj)
        mesh, data = atlas.mesh(fj)
        header = {}
        for line in data.split(b"\n", 12)[:12]:
            match = re.match(rb"# (Compatibility version|File ID|Representation ID|Build-up logic|Concept ID"
                             rb"|English name|Bounds\(mm\))\s*:\s*(.+)", line)
            if match:
                header[match[1].decode()] = match[2].decode()
        assert header["File ID"] == fj and header["Compatibility version"] == "4.3"
        assert header["Concept ID"] == mesh["obj_concept_id"]
        assert header["Representation ID"] == mesh["obj_representation_id"]
        samples.append({"concept": concept, "fj": fj, "claims": member["claims"], "obj_header_fields": header,
                        "memberships": member["memberships"], "pack": member["pack"],
                        "mesh_sha256": member["mesh_sha256"],
                        "bp_conflict": member["bp_conflict"], "fma_conflict": member["fma_conflict"]})
    print(json.dumps({"status": "PASS", "sha256": unique, "objs_verified": len(atlas.catalog["meshes"]),
                      "packs_verified": len(packs), "coverage": atlas.coverage(), "samples": samples}, indent=2))


if __name__ == "__main__":
    main()
