"""Normalize retained source records without asserting new anatomy edges."""
import csv
import hashlib
import html
import re
from collections import Counter

from fetch_mirror import pinned_inventory

ARCHIVE = "https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/"
ORIG = "https://lifesciencedb.jp/bp3d/"
PIN = "fd527e6f4daf732fd814314d9257df5877b844bc"
RAW = f"https://raw.githubusercontent.com/olivercase/body_parts_3d_api/{PIN}/"
SHA_RE = re.compile(r"FMA(\d+)$")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fma(value):
    return int(SHA_RE.fullmatch(value).group(1))


def tsv(up, name):
    with (up / name).open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def side(label):
    sides = set(re.findall(r"\b(left|right)\b", label.lower()))
    return next(iter(sides)) if len(sides) == 1 else "unknown"


def obj2fma(up, pins):
    allowed = {p["fj_id"] for p in pins}
    body = (up / "mirror-obj2FMA.html").read_text(encoding="utf-8")
    rows = {}
    for row in re.findall(r"<tr>\s*(.*?)\s*</tr>", body, re.S):
        values = {key: html.unescape(value).strip() for key, value in
                  re.findall(r'<td class="([^"]+)">(.*?)</td>', row, re.S)}
        if values.get("art_id") in allowed:
            fj = values["art_id"]
            assert fj not in rows, fj
            rows[fj] = values
    assert rows.keys() == allowed
    return rows


def membership(up, filename, source_id):
    lines = (up / filename).read_text(encoding="utf-8").splitlines()
    definitions = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        concept, mapping, elements = line.split("\t")
        assert mapping in {"is_a", "part_of"}
        identifiers = elements.split("+")
        assert len(identifiers) == len(set(identifiers))
        definitions.extend({"fma_id": fma(concept), "fj_id": fj,
                            "mapping": mapping, "source_id": source_id} for fj in identifiers)
    return definitions


def source(up, source_id, version, url, file, license_name, **metadata):
    path = up / file
    return {"id": source_id, "version": version, "url": url, "sha256": digest(path),
            "bytes": path.stat().st_size, "license": license_name, **metadata}


def build(up):
    copy_license = "CC-BY-SA-2.1-JP"
    attribution = "BodyParts3D, © The Database Center for Life Science (DBCLS)"
    metadata_terms = ORIG + "info_en/index.html#License"
    official_license = "https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html"
    sources = [
        source(up, "bp3d_43_meshes", "4.3", f"https://codeload.github.com/olivercase/body_parts_3d_api/zip/{PIN}",
               "mirror-fd527e6.zip", copy_license, revision=PIN, attribution=attribution,
               license_url="https://creativecommons.org/licenses/by-sa/2.1/jp/",
               artifact_kind="Git LFS pointer ZIP; OBJ digests pinned individually"),
        source(up, "bp3d_43_primary", "4.3-filtered-master", RAW + "metadata/obj2FMA.html", "mirror-obj2FMA.html",
               "REDISTRIBUTION_UNCONFIRMED", revision=PIN, attribution=attribution,
               license_url=metadata_terms,
               artifact_kind="version-spanning primary labels and object crosswalk restricted to stamped 4.3 FJ IDs"),
        source(up, "bp3d_43_components", "4.3",
               ORIG + "get-info.cgi?version=4.3&cmd=concept-objfiles-list", "original-FMA2Obj-43.txt",
               "REDISTRIBUTION_UNCONFIRMED", license_url=metadata_terms,
               attribution=attribution, tree_version="FMA3.0",
               zip_sha256=digest(up / "original-FMA2Obj-43.zip"), artifact_kind="geometry representation memberships"),
        source(up, "bp3d_43i_components", "4.3i",
               ORIG + "get-info.cgi?version=4.3i&cmd=concept-objfiles-list", "original-FMA2Obj-43i.txt",
               "REDISTRIBUTION_UNCONFIRMED", license_url=metadata_terms,
               attribution=attribution, tree_version="FMA3.2.1-inference",
               zip_sha256=digest(up / "original-FMA2Obj-43i.zip"), artifact_kind="geometry representation memberships"),
    ]
    for prefix, predicate in (("isa", "IS-A"), ("partof", "PART-OF")):
        for kind, suffix in (("edges", "inclusion_relation_list.txt"), ("labels", "parts_list_e.txt")):
            name = f"{prefix}_{suffix}"
            sources.append(source(up, f"bp3d_archive_{prefix}_{kind}", "DBCLS LATEST 4.0 distribution", ARCHIVE + name,
                                  name, "CC-BY-4.0", license_url=official_license, attribution=attribution,
                                  ontology_version="unspecified", predicate=predicate))

    pins = pinned_inventory(up)
    primary = obj2fma(up, pins)
    labels = {}
    meshes = []
    label_conflicts = []
    identity_conflicts = []
    for pin in pins:
        fj = pin["fj_id"]
        meta = primary[fj]
        concept = fma(meta["cdi_name"])
        label = meta["cdi_name_e"]
        assert label
        if concept in labels and labels[concept]["label"] != label:
            label_conflicts.append({"fma_id": concept, "fj_id": fj, "label": label,
                                    "retained_label": labels[concept]["label"]})
        labels.setdefault(concept, {"label": label, "side": side(label), "source_id": "bp3d_43_primary"})
        pinned_concept = fma(pin["source_primary_fma"])
        if pinned_concept != concept:
            identity_conflicts.append({"fj_id": fj, "master_fma_id": concept,
                                       "pinned_filename_fma_id": pinned_concept})
        meshes.append({"fj_id": fj, "bp_id": meta["rep_id"], "fma_id": concept, "label": label,
                       "side": side(label), "filename": pin["filename"], "bytes": pin["size"], "sha256": pin["oid"],
                       "source_id": "bp3d_43_meshes", "identity_source_id": "bp3d_43_primary",
                       "identity_status": "DISPUTED" if pinned_concept != concept else "MATCH",
                       "pinned_filename_fma_id": pinned_concept,
                       "representation": "source_mesh", "historical_mirror_component": fj.endswith("M")})
    components = []
    for version, source_id in (("43", "bp3d_43_components"), ("43i", "bp3d_43i_components")):
        entries = membership(up, f"original-FMA2Obj-{version}.txt", source_id)
        assert {r["fj_id"] for r in entries} == primary.keys()
        components.extend(entries)
    components.extend({"fma_id": r["fma_id"], "fj_id": r["fj_id"], "mapping": "primary",
                       "source_id": r["identity_source_id"]} for r in meshes)
    relations = []
    counts = Counter()
    for prefix, predicate in (("isa", "is_a"), ("partof", "part_of")):
        for row in tsv(up, f"{prefix}_parts_list_e.txt"):
            concept = fma(row["concept id"])
            label = row["en"]
            labels.setdefault(concept, {"label": label, "side": side(label),
                                        "source_id": f"bp3d_archive_{prefix}_labels"})
        for row in tsv(up, f"{prefix}_inclusion_relation_list.txt"):
            parent = fma(row["parent id"])
            child = fma(row["child id"])
            source_id = f"bp3d_archive_{prefix}_edges"
            for concept, label in ((parent, row["parent name"]), (child, row["child name"])):
                labels.setdefault(concept, {"label": label, "side": side(label), "source_id": source_id})
            relations.append({"subject_fma": child, "predicate": predicate, "object_fma": parent,
                              "source_id": source_id, "inferred": False})
            counts[predicate] += 1
    for row in components:
        concept = row["fma_id"]
        labels.setdefault(concept, {"label": f"FMA{concept}", "side": "unknown", "label_status": "identifier_only",
                                    "source_id": row["source_id"]})
    assert len({(r["fma_id"], r["fj_id"], r["mapping"], r["source_id"]) for r in components}) == len(components)
    assert len({(r["subject_fma"], r["predicate"], r["object_fma"], r["source_id"]) for r in relations}) == len(relations)
    concepts = [{"fma_id": concept, **label} for concept, label in sorted(labels.items())]
    by_fj = {r["fj_id"]: r for r in meshes}
    assert [(by_fj[fj]["fma_id"], by_fj[fj]["side"]) for fj in ("FJ3368", "FJ3262")] == [(23130, "right"), (23131, "left")]
    assert not any(r["inferred"] or "43i" in r["source_id"] for r in relations)
    catalog = {
        "schema_version": 1,
        "manifest": {
            "atlas_id": "BodyParts3D",
            "version": "4.3",
            "mesh_dir": "meshes",
            "expected_source_fj": len(meshes),
            "inferred_43i_coverage": "PARTIAL",
            "inferred_43i_edges_received": 0,
            "coordinate_frame": {"id": "bp3d-43-source", "unit": "mm", "handedness": "right",
                                 "axes": {"x": "patient_left", "y": "posterior", "z": "superior"},
                                 "status": "inferred_source_convention_not_human_validated"},
            "primary_label_conflicts": label_conflicts,
            "primary_identity_conflicts": identity_conflicts,
        },
        "sources": sources, "concepts": concepts, "meshes": meshes, "components": components, "relations": relations,
    }
    return catalog, counts

