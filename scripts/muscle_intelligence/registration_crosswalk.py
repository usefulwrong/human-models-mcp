"""Extend the pinned v2 crosswalk without changing any approved overlay."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from anatomy_lab import canonical, digest, read_bounded
from crosswalk import ACCEPTED, NOMENCLATURE, name_key, source_labels, source_side

DOC = "https://myosuite.readthedocs.io/en/stable/suite.html"
NATIVE = "https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700"
# Model-family hypotheses require the indicated native route and XML component.
NATIVE_FAMILIES = (
    (r"LD_(?:[LTR]\d+|IL)", "Arm", "latissimus dorsi", (r"humerus_[rl]", r"thoracic\d+|lumbar\d+|pelvis|rib\d+_[RL]")),
    (r"ExtIC_IS\d+_\d+", "Torso", "external intercostal", (r"rib\d+_[RL]", r"rib\d+_[RL]")),
    (r"IntIC_IS\d+_\d+", "Torso", "internal intercostal", (r"rib\d+_[RL]", r"rib\d+_[RL]")),
    (r"multifidus_[LT]\d+_[LT]\d+", "Torso", "multifidus", (r"lumbar\d+|thoracic\d+",) * 2),
    (r"(?:sup|deep)mult-[CT]\d+-[CT]\d+", "Torso", "multifidus", (r"head_neck|thoracic\d+",) * 2),
    (r"SerrAnt\d+_\d+", "Torso", "serratus anterior", (r"rib\d+_[RL]", r"scapula_[rl]")),
    (r"TR[1-5]", "Torso", "transversus abdominis", (r"Abdomen", r"rib\d+_[RL]|pelvis")),
)
HAND = {"FDS": "flexor digitorum superficialis", "FDP": "flexor digitorum profundus",
        "EDC": "extensor digitorum"}
FAMILY_PATTERN = r"^(?:long head|short head|lateral head|medial head|clavicular part|acromial part|spinal part) of "


def find_family(row, names, model_files):
    path = row["canonical"]
    stem, side = path["stem"], row["side"]
    key = row["exact_name"]
    sites = row["route_evidence"]["endpoints"]
    bodies = [s["body"] for s in sites]
    files = {file: model_files[file] for file in row["source_actuator_files"] if file in model_files}
    if row["group"]:
        return row["group"].split(":")[0].replace("_", " "), "REVIEWED_GROUP", row["reference"], []
    if path["source_label"]:
        label = re.sub(FAMILY_PATTERN, "", path["source_label"].lower())
        return re.sub(r"^(left|right|unknown) ", "", label), "PINNED_NOMENCLATURE", DOC, path["pinned_name_matches"]
    if any("Muscle_Torso" in name for name in files):
        # MS-Human changes dot separators and rib tokens in these particular source namespaces.
        normalized = re.sub(r"(?<=-)R(?=\d)", "", key.replace(".", "_"))
        matches = [item for item in names.get(normalized, []) if item["component"] == "torso"]
        torso = {"QL_": "quadratus lumborum", "MF_": "multifidus", "EO_": "external oblique", "IO": "internal oblique"}
        label = next((label for prefix, label in torso.items() if stem.startswith(prefix)), None)
        if label:
            if not matches:
                matches = [item for item in names.get(stem, []) if item["component"] == "torso"
                           and source_side(item["name"]) == side]
            return label, "PINNED_NOMENCLATURE" if matches else "NATIVE_FAMILY_CANDIDATE", DOC, matches
    digit = re.fullmatch(r"(FDS|FDP|EDC)[LRMI]", stem)
    if digit and any("Muscle_Arm" in file for file in files) and len(sites) == 2 and bodies[-1] == f"hand_{key[-1]}":
        return HAND[digit[1]], "NATIVE_FAMILY_CANDIDATE", DOC, []
    for pattern, component, label, route in NATIVE_FAMILIES:
        if (re.fullmatch(pattern, stem) and any(f"Muscle_{component}" in file for file in files)
                and len(bodies) == 2 and all(re.fullmatch(p, b) for p, b in zip(route, bodies, strict=True))):
            return label, "NATIVE_FAMILY_CANDIDATE", NATIVE, []
    return None, "UNRESOLVED", None, []


def upgrade(v2, catalog, names, model_files):
    prior = v2["counts"]
    label_index = defaultdict(list)
    for c in catalog["concepts"]:
        label = re.sub(r"^(?:left|right) ", "", c["label"], flags=re.I)
        normalized = re.sub(r" (?:muscle|muscles)$", "", name_key(label))
        label_index[normalized].append(c)
    by_family = defaultdict(list)
    moving_by_concept = defaultdict(list)
    mesh_by_concept = defaultdict(list)
    for node, asset in v2["motion_display_assets"].items():
        moving_by_concept[(asset.get("fma_id"), asset["side"])].append(int(node))
    for mesh in catalog["meshes"]:
        mesh_by_concept[(f"FMA{mesh['fma_id']}", mesh["side"])].append(mesh)
    for row in v2["rows"]:
        family, grade, url, matches = find_family(row, names, model_files)
        if family:
            by_family[family].append(row["id"])
        proposals = row["concept_membership"]
        if family and not proposals:
            concepts = label_index[family]
            # A family-level unsided concept never resolves patient side or a segment.
            for c in concepts:
                if c["side"] in (row["side"], "unknown"):
                    proposals.append({"fma_id": f"FMA{c['fma_id']}", "label": c["label"], "side": c["side"],
                                      "source": c["source_id"], "status": "CANDIDATE", "scope": "FAMILY_ONLY",
                                      "synonyms": [], "part_of": []})
            if proposals:
                row["status"] = row["status_axes"]["anatomical_concept"] = "CANDIDATE"
                row["reason_codes"] = [r for r in row["reason_codes"] if r != "NO_SIDED_CATALOG_TARGET"]
                row["reason_codes"].append("FAMILY_CONCEPT_ONLY_SEGMENT_REVIEW_REQUIRED")
        if row["side"] == "unknown":
            row["reason_codes"].append("SIDE_NOT_DECLARED_IN_NATIVE_ID")
        if not family:
            row["reason_codes"].append("NO_DEFENSIBLE_FAMILY_EXPANSION")
        if family and grade == "NATIVE_FAMILY_CANDIDATE":
            row["reason_codes"].append("SOURCE_ROUTE_FAMILY_HYPOTHESIS")
        if not proposals:
            row["reason_codes"].append("NO_CATALOG_CONCEPT_FOR_PATH")
        accepted = [c for c in proposals if c["status"] == ACCEPTED]
        if row["group"] and (any(c["side"] != row["side"] for c in accepted)
                             or row["geometry_check"]["expected"] != row["geometry_check"]["observed"]):
            raise ValueError(f"prior acceptance contradicts side or route: {row['exact_name']}")
        candidate_keys = [(c["fma_id"], row["side"]) for c in proposals if c["status"] == "CANDIDATE"]
        row["registration_review"] = {
            "family": family, "family_evidence": grade, "family_source": url, "matched_source_ids": matches,
            "model_xml_sha256": {f: model_files[f] for f in row["source_actuator_files"] + row["source_tendon_files"]},
            "fma": "REVIEWED" if accepted else "CANDIDATE" if proposals else "NONE",
            "candidate_geometry": {"moving_nodes": sorted({n for k in candidate_keys for n in moving_by_concept[k]}),
                                   "bodyparts3d": [{"fj_id": m["fj_id"], "sha256": m["sha256"],
                                                    "identity_status": m["identity_status"]}
                                                   for k in candidate_keys for m in mesh_by_concept[k]]},
            "acceptance": {"carried_from": 2, "region": row["region"], "side": row["side"],
                           "joint": row["review_joint"], "endpoints": row["geometry_check"]["observed"],
                           "concepts": [c["fma_id"] for c in accepted], "group": row["group"]}
            if row["group"] else None,
            "attachment_footprint": "NOT_VERIFIED", "deformation_validation": "NOT_VERIFIED",
            "review_needed": ["INDEPENDENT_ATTACHMENT_FOOTPRINT"] if accepted else [
                "SEGMENT_AND_SOURCE_CONCEPT_REVIEW", "INDEPENDENT_ATTACHMENT_FOOTPRINT"],
        }
    v2["coverage_revision"] = 3
    v2["anatomical_families"] = dict(sorted(by_family.items()))
    v2["authored_43i_inferred_relations"] = "NOT_VERIFIED"
    v2["counts"] = {**prior, "statuses": dict(Counter(r["status"] for r in v2["rows"])),
                    "family_label_supported": sum(len(ids) for name, ids in by_family.items()),
                    "family_evidence": dict(Counter(r["registration_review"]["family_evidence"] for r in v2["rows"])),
                    "independently_registered_attachments": 0, "independent_human_validations": 0}
    return v2


def build(args):
    raw = read_bounded(args.v2, 8 << 20)
    catalog = read_bounded(args.catalog, 64 << 20)
    v2 = json.loads(raw)
    if digest(raw) != args.v2_sha256 or v2["coverage_revision"] != 2 or len(v2["rows"]) != 700:
        raise ValueError("v2 revision or digest mismatch")
    if digest(catalog) != v2["anatomy_revision"] or digest(NOMENCLATURE.read_bytes()) != v2["nomenclature_sha256"]:
        raise ValueError("catalog or nomenclature revision mismatch")
    _, source = source_labels(args.myo_sim)
    # Index only the pinned XML actuator table. Preserve the original spelling in each receipt.
    names = defaultdict(list)
    for items in source.values():
        for item in items:
            name = item["name"]
            for lookup in {name, name.replace(".", "_"), re.sub(r"_[rl]$", "", name)}:
                if item not in names[lookup]:
                    names[lookup].append(item)
    lock = json.loads(read_bounded(args.model.parent.parent / "models.lock.json", 256 << 10))
    if lock["asset_sha256"] != v2["source_model_sha256"] or digest(canonical(lock["files"])) != lock["asset_sha256"]:
        raise ValueError("model pin differs")
    model_pins = {f["path"].removeprefix(args.model.name + "/"): f["sha256"] for f in lock["files"]}
    files = {}
    for row in v2["rows"]:
        for file in row["source_actuator_files"] + row["source_tendon_files"]:
            if file not in files:
                payload = read_bounded(args.model / file, 4 << 20)
                files[file] = digest(payload)
                if files[file] != model_pins.get(file):
                    raise ValueError(f"model XML SHA-256 differs: {file}")
                ET.fromstring(payload)
    result = upgrade(v2, json.loads(catalog), names, files)
    result["prior_crosswalk_sha256"] = args.v2_sha256
    result["registration_rules_sha256"] = digest(Path(__file__).read_bytes())
    args.output.write_bytes(canonical(result) + b"\n")
    print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("v2", "catalog", "myo_sim", "model", "output"):
        parser.add_argument("--" + field.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--v2-sha256", required=True)
    build(parser.parse_args())
