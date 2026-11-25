"""Inventory the compiled pin and associate source concepts without transferring geometry."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import mujoco as mj
import numpy as np

from anatomy_lab import canonical, digest, read_bounded
from glb import array, unpack
from human_models_mcp.registry import home
from human_models_mcp.scene_export import load_saved_run
from human_models_mcp.adapters.mujoco import moment_entry

ACCEPTED = "REVIEWED_ANATOMICAL"
SCHEMA = "hmm.muscle.crosswalk/1"
NOMENCLATURE = Path(__file__).with_name("SOURCE_ABBREVIATIONS.json")


def unique(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate {key}")
    return result


def name_key(name):
    return " ".join(re.findall(r"[a-z]+", name.casefold()))


def source_side(name):
    match = re.search(r"_(r|l|R|L)$", name)
    return {"r": "right", "l": "left"}.get(match[1].lower(), "unknown") if match else "unknown"


def source_labels(root):
    table = json.loads(NOMENCLATURE.read_bytes())
    names = defaultdict(list)
    for component, filename in table["files"].items():
        raw = read_bounded(root / filename, 2 << 20)
        sha = table["file_sha256"][component]
        if digest(raw) != sha:
            raise ValueError(f"unexpected upstream nomenclature pin: {filename}")
        for item in ET.fromstring(raw).findall(".//actuator/*"):
            name = item.attrib["name"]
            stem = re.sub(r"_[rl]$", "", name)
            for token in sorted({name, stem}):
                names[token].append({"component": component, "name": name, "file": filename, "sha256": sha})
    return table, names


def canonical_path(row, table, names):
    name, side = row["exact_name"], row["side"]
    stem = name[:-2] if side != "unknown" else name
    scopes = {"Leg": "leg", "Torso": "torso", "Arm": "arm"}
    component = next((value for key, value in scopes.items()
                      if any(f"Muscle_{key}" in path for path in row["source_actuator_files"])), None)
    matched = [item for item in names.get(stem, []) if item["component"] == component
               and (source_side(item["name"]) in (side, "unknown"))]
    if not matched and stem.startswith("Ps_"):
        matched = names.get(name, [])
    entries = table["labels"].get(matched[0]["component"] if matched else component, {})
    expansion = next((label.format(side=side) for pattern, label in entries.items()
                      if re.fullmatch(pattern, stem)), None) if matched else None
    levels = re.findall(r"(?:^|[_-])([CTLRS][0-9]{1,2})(?=$|[_-])", stem)
    digit = re.fullmatch(r"(?:FDS|FDP|EDC)([LRMI])", stem)
    region = ("spine" if stem.startswith(("IL_", "LTp", "QL_", "MF_", "Ps_")) else
              "torso" if component == "torso" or stem.startswith(("LD_", "PECM")) else
              "pelvis" if component == "leg" and stem.startswith(("add", "gl", "ilia", "piri", "tfl")) else
              "leg_foot" if component == "leg" else
              "shoulder" if component == "arm" and stem.startswith(("DELT", "SUPSP", "INFSP", "SUBSC", "TMIN", "TMAJ"))
              else "arm_hand" if component == "arm" else "unknown")
    return {"stem": stem, "side_token": name[-1] if side != "unknown" else None,
            "sex_token": None, "tokens": re.findall(r"[A-Za-z]+|[0-9]+|[^A-Za-z0-9]", stem),
            "vertebral_or_rib_tokens": levels, "digit": {"L": 5, "R": 4, "M": 3, "I": 2}[digit[1]] if digit else None,
            "head_or_segment_tokens": re.findall(r"long|short|lat|med|Dist|Isch|Mid|Prox|post|mid|ant|laminar|[0-9]+", stem),
            "region": region, "source_label": expansion, "pinned_name_matches": matched}


def recorded_moments(model, run, manifest, anchors):
    """Rank the observed sparse Jacobian terms at each saved anchor."""
    out = {}
    start = 0
    for name in manifest["outputs"]["muscles"]["chunks"]:
        with np.load(run / name, allow_pickle=False) as pack:
            values, cols, adr, counts = (pack[k] for k in
                                         ("moment_values", "moment_columns", "moment_rowadr", "moment_rownnz"))
        for index in anchors:
            i = index - start
            if not 0 <= i < len(values):
                continue
            for aid in range(model.nu):
                terms = sorted(((float(values[i, j]), int(cols[i, j]))
                                for j in range(adr[i, aid], adr[i, aid] + counts[i, aid])
                                if values[i, j] != 0), key=lambda pair: -abs(pair[0]))
                out.setdefault(aid, {})[index] = {"nonzero_dofs": len(terms), "largest": [
                    {"dof": dof, "joint": model.joint(int(model.dof_jntid[dof])).name, "dL_dq": value}
                    for value, dof in terms[:4]]}
        start += len(values)
    if len(out) != model.nu or any(len(items) != len(anchors) for items in out.values()):
        raise ValueError("missing saved moment-arm anchors")
    return out


def candidates(name, side, aliases, index):
    stem = re.sub(r"_[rl]$", "", name, flags=re.I)
    for prefix, label in aliases.items():
        if re.fullmatch(re.escape(prefix) + r"(?:[0-9]+|Dist|Isch|Mid|Prox|long|short|_(?:L[1-5]_.*))?", stem, re.I):
            return index.get((side, name_key(label)), [])
    return index.get((side, name_key(stem)), [])


def bodyparts_asset(concept, row, dataset, memberships):
    fma_id = concept["fma_id"]
    rows = memberships.get((fma_id, row["fj_id"]), [])
    status = ("conflicting" if row["identity_status"] != "MATCH" or row["pinned_filename_fma_id"] != fma_id
              or row["side"] != concept["side"] else "primary")
    return {"dataset": "BodyParts3D", "dataset_revision": dataset["revision"], "mesh_id": row["fj_id"],
            "bp_id": row["bp_id"], "name": row["label"], "side": row["side"], "fma_id": f"FMA{fma_id}",
            "geometry_sha256": row["sha256"], "display_copy": None,
            "pinned_filename_fma_id": row["pinned_filename_fma_id"], "source_membership": status,
            "catalog_memberships": rows, "source": dataset["url"]}


def display_asset(row, source, source_blob, glb, rules, concept, bp):
    original = source["nodes"][row["source_node"]]
    bare_name = re.sub(r" \[FJ\d+M?\]$", "", original["name"])
    if not (original["name"] == row["name"] and name_key(bare_name) == name_key(concept["label"])
            and row["fma_id"] == bp["fma_id"] and bp["source_membership"] == "primary"
            and row["crosswalk"] == "MATCH" and bp["side"] == concept["side"]):
        raise ValueError("display identity conflict")
    prim, = source["meshes"][original["mesh"]]["primitives"]
    attrs = prim["attributes"]
    vals = [array(source, source_blob, attrs[attr]) for attr in ("POSITION", "JOINTS_0", "WEIGHTS_0")]
    payload = vals[0].tobytes() + array(source, source_blob, prim["indices"]).tobytes()
    payload += vals[1].tobytes() + vals[2].tobytes()
    if digest(payload) != row["source_mesh_sha256"]:
        raise ValueError("source display geometry SHA-256 differs")
    node = glb["nodes"][row["node"]]
    if (node["name"] != row["name"] or node["extras"]["source_node"] != row["source_node"]
            or node["extras"]["layer"] != "MUSCLES" or node["extras"]["fma_id"] != row["fma_id"]):
        raise ValueError("display copy node differs")
    return {"dataset": "MyoSuite", "dataset_revision": rules["myosuite_revision"],
            "mesh_id": f"myosuite:{row['source_node']}", "source_node": row["source_node"],
            "fj_label": row["fj_id"], "name": original["name"], "side": concept["side"],
            "fma_id": row["fma_id"], "geometry_sha256": row["source_mesh_sha256"],
            "display_copy": row["node"], "source_membership": "label_and_catalog_agreement",
            "deformation": row["mode"], "attachment_validation": "NOT_VERIFIED"}


def inventory(model, model_dir):
    definitions = {}
    for folder, selector in [("muscle", ".//actuator/*"), ("tendon", ".//tendon/*"),
                             ("body_primary", ".//site"), ("body_manipulation", ".//site")]:
        for path in sorted((model_dir / "assets" / folder).glob("*.xml")):
            for item in ET.parse(path).findall(selector):
                if item.get("name"):
                    definitions.setdefault(item.get("name"), []).append(str(path.relative_to(model_dir)))
    for i in range(model.nu):
        act = model.actuator(i)
        tendon = int(model.actuator_trnid[i, 0])
        if model.actuator_trntype[i] != mj.mjtTrn.mjTRN_TENDON:
            raise ValueError(f"unexpected transmission for {act.name}")
        name = model.tendon(tendon).name
        links = []
        adr = model.tendon_adr[tendon]
        for j in range(adr, adr + model.tendon_num[tendon]):
            kind = mj.mjtWrap(int(model.wrap_type[j])).name.removeprefix("mjWRAP_").lower()
            obj = int(model.wrap_objid[j])
            link = {"link_id": int(j), "kind": kind, "object_id": obj}
            if kind == "site":
                site = model.site(obj)
                link.update(name=site.name, body=model.body(int(model.site_bodyid[obj])).name,
                            body_local_m=site.pos.tolist(), source_files=definitions.get(site.name, []))
            elif kind in {"sphere", "cylinder"}:
                sid = int(model.wrap_prm[j])
                link.update(name=model.geom(obj).name, body=model.body(int(model.geom_bodyid[obj])).name,
                            sidesite_id=sid, sidesite=model.site(sid).name if sid >= 0 else None)
            else:
                link["parameter"] = float(model.wrap_prm[j])
            links.append(link)
        yield {"id": i, "exact_name": act.name, "side": source_side(act.name),
               "tendon_id": tendon, "tendon_name": name, "links": links,
               "source_actadr": int(model.actuator_actadr[i]), "motion_availability": "RECORDED",
               "source_actuator_files": definitions.get(act.name, []),
               "source_tendon_files": definitions.get(name, [])}


def check_moments(model, data, states, spec, rows):
    checks = []
    for row in rows:
        a = row["id"]
        side = row["exact_name"][-1]
        joint = model.joint(row["review_joint"] + "_" + side)
        q, dof = int(joint.qposadr[0]), int(joint.dofadr[0])
        for i in (0, 55, 110):
            mj.mj_setState(model, data, states[i], spec)
            mj.mj_forward(model, data)
            exact = moment_entry(model, data, a, dof)
            center = data.qpos[q]
            step = 1e-6
            values = []
            for sign in (-1, 1):
                data.qpos[q] = center + sign * step
                mj.mj_forward(model, data)
                values.append(float(data.actuator_length[a]))
            finite = (values[1] - values[0]) / (2 * step)
            checks.append({"name": row["exact_name"], "state_index": i, "hinge": joint.name, "step_rad": step,
                           "native_dL_dq_m_per_rad": exact, "finite_difference_m_per_rad": finite,
                           "absolute_error_m_per_rad": abs(exact - finite)})
    return checks


def build(args):
    rules = json.loads(args.rules.read_bytes())
    table, names = source_labels(args.myo_sim)
    catalog_raw = read_bounded(args.catalog, 64 << 20)
    source_raw = read_bounded(args.myo, 32 << 20)
    motion_raw = read_bounded(args.clip / "motion.json", 1 << 20)
    motion = json.loads(motion_raw)
    if digest(catalog_raw) != rules["catalog_sha256"] or motion["catalog_sha256"] != rules["catalog_sha256"]:
        raise ValueError("anatomy catalog revision mismatch")
    if digest(source_raw) != rules["myosuite_sha256"]:
        raise ValueError("MyoSuite revision mismatch")
    manifest_raw = read_bounded(args.run / "manifest.json", 1 << 20)
    manifest = json.loads(manifest_raw)
    if (digest(manifest_raw) != motion["source_manifest_sha256"] or manifest["run_id"] != args.run.name
            or manifest["run_id"] != motion["run_id"] or manifest["model"]["asset_sha256"] != rules["model_sha256"]):
        raise ValueError("source model, manifest or run identity mismatch")
    for name in ("actuators.json", "model_recipe.json", "trajectory.npz", "series.csv",
                 "summary.json", "trajectory_metadata.json", *manifest["outputs"]["muscles"]["chunks"]):
        raw = read_bounded(args.run / name, 8 << 20)
        record = manifest["artifacts"][name]
        if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
            raise ValueError(f"source artifact digest differs: {name}")
    run, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(args.run)
    raw_model = mj.MjModel.from_xml_path(str(home() / "models/ms_human_700/scene.xml"))
    saved = json.loads((args.run / "actuators.json").read_bytes())["actuators"]
    model_dir = home() / "models/ms_human_700"
    rows = list(inventory(model, model_dir))
    raw = list(inventory(raw_model, model_dir))
    if (len(rows) != 700 or len(raw) != 700 or len({r["exact_name"] for r in rows}) != 700
            or [(r["id"], r["exact_name"], r["tendon_id"], r["source_actadr"]) for r in rows] !=
            [(r["id"], r["name"], r["tendon_id"], r["actadr"]) for r in saved]
            or [r["exact_name"] for r in rows] != [r["exact_name"] for r in raw]):
        raise ValueError("compiled and recorded actuator inventory mismatch")
    catalog = json.loads(catalog_raw)
    concepts = unique(catalog["concepts"], "fma_id")
    by_label = defaultdict(list)
    for concept in concepts.values():
        by_label[(concept["side"], concept["label"].casefold())].append(concept)
    part_of = defaultdict(list)
    for edge in catalog["relations"]:
        if edge["predicate"] == "part_of":
            part_of[edge["subject_fma"]].append(edge)
    mesh_index = unique(catalog["meshes"], "fj_id")
    dataset = unique(catalog["sources"], "id")["bp3d_43_meshes"]
    memberships, mesh_by_fma, concept_by_name = defaultdict(list), defaultdict(list), defaultdict(list)
    for member in catalog["components"]:
        memberships[(member["fma_id"], member["fj_id"])].append(member)
    for mesh in mesh_index.values():
        mesh_by_fma[mesh["fma_id"]].append(mesh)
    for concept in concepts.values():
        label = re.sub(r"\b(?:left|right|muscle|of)\b", "", concept["label"], flags=re.I)
        concept_by_name[(concept["side"], name_key(label))].append(concept)

    clips = {}
    for name, size in (("coverage.json", 4 << 20), ("motion.glb", 32 << 20)):
        clips[name] = read_bounded(args.clip / name, size)
        if digest(clips[name]) != motion["artifacts"][name]["sha256"]:
            raise ValueError("MotionScene artifact SHA-256 differs")
    coverage = json.loads(clips["coverage.json"])
    glb, _ = unpack(clips["motion.glb"])
    source, source_blob = unpack(source_raw)
    display = unique([r for r in coverage["source_surfaces"] if "node" in r], "source_node")
    display_names = unique(list(display.values()), "name")
    moments = recorded_moments(model, args.run, manifest, (0, 55, 110))
    assets = []
    groups = {}
    for row, upstream, record in zip(rows, raw, saved, strict=True):
        native = row["exact_name"]
        side = row["side"]
        row.update(model_sha256=rules["model_sha256"], coarse_group=record["group"],
                   raw_model_transmission={"tendon_id": upstream["tendon_id"],
                                           "link_names": [link.get("name") for link in upstream["links"]]},
                   status="UNMAPPED" if row["links"] else "NO_SOURCE_GEOMETRY",
                   group=None, concept_membership=[], bodyparts3d=[], display_assets=[],
                   relationship="unresolved", cardinality="zero_reviewed",
                   evidence_grade="native_only", geometry_check="NOT_CHECKED",
                   usable={"per_actuator_plot": True, "group_plot": False, "color": False, "deformation": False})
        path = canonical_path(row, table, names)
        endpoints = [item for item in row["links"] if item["kind"] == "site"]
        row.update(canonical=path, region=path["region"], route_evidence={
            "endpoints": [endpoints[0], endpoints[-1]] if endpoints else [],
            "observed_dL_dq": moments[row["id"]], "scope": "native body-local sites and saved transmission derivatives",
        })
        proposal = by_label[(side, path["source_label"].casefold())] if path["source_label"] else []
        if not proposal:
            proposal = candidates(native, side, rules["candidate_aliases"], concept_by_name)
        reasons = ["PINNED_NATIVE_TENDON"]
        if path["pinned_name_matches"]:
            reasons.append("PINNED_MYOSIM_IDENTIFIER")
        labels = rules["reviewed"].get(native[:-2]) if side != "unknown" else None
        if labels:
            group, part, first, last, *joint = labels
            approved_source = not joint or bool(path["source_label"] and path["pinned_name_matches"])
            row["review_joint"] = joint[0] if joint else (
                "elv_angle" if group == "pectoralis_major" else "elbow_flexion")
            fmt = {"side": side, "suffix": native[-1]}
            expected = [s.format(**fmt) for s in (first, last)]
            observed = [endpoints[0]["body"], endpoints[-1]["body"]]
            endpoints_agree = observed == expected and all(
                link["body"] in ("sternum", "pelvis") or source_side(link["body"]) == side for link in endpoints)
            parent = next((c for c in concepts.values()
                           if c["label"].casefold() == f"{side} {group.replace('_', ' ')}"), None)
            label = part.format(**fmt) if part else None
            proposal = by_label[(side, label.casefold())] if label else []
            if not part:
                proposal = [c for c in concepts.values() if c["label"] == f"Abdominal part of {side} pectoralis major"]
            if not approved_source or not endpoints_agree or len(proposal) != 1 or proposal[0]["side"] != side:
                row.update(status="CONFLICT", geometry_check={"expected": expected, "observed": observed})
                reasons.append("REVIEW_RULE_PREREQUISITE_FAILED")
            else:
                key = f"{group}:{side}"
                obj = groups.setdefault(key, {"group_id": key, "name": group.replace("_", " "), "side": side,
                    "parent_fma_id": f"FMA{parent['fma_id']}" if parent else None, "actuator_ids": []})
                obj["actuator_ids"].append(row["id"])
                reasons.append("REVIEWED_SIDED_LABEL_AND_ROUTE")
                row.update(status=ACCEPTED, group=key, relationship="split_path",
                           cardinality="multiple_native_paths_per_sided_group",
                           evidence_grade="native_name_and_endpoint_bodies",
                           geometry_check={"expected": expected, "observed": observed, "mesh_attachments": "NOT_VERIFIED"},
                           reference=rules["sources"][group],
                           note=("Group identity supported. Caudal site is on sternum; abdominal aponeurosis is unverified."
                                 if not part else "Model part identity supported; surface placement remains illustrative."))
                row["usable"]["group_plot"] = True
        elif proposal:
            row.update(status="CANDIDATE", evidence_grade="name_and_catalog_side")
        for c in proposal:
            identity = {"fma_id": f"FMA{c['fma_id']}", "label": c["label"], "side": c["side"],
                        "source": c["source_id"], "synonyms": [],
                    "status": ACCEPTED if labels and labels[1] and row["status"] == ACCEPTED else "CANDIDATE",
                    "part_of": part_of[c["fma_id"]]}
            row["concept_membership"].append(identity)
            for mesh in mesh_by_fma[c["fma_id"]]:
                bp = bodyparts_asset(c, mesh, dataset, memberships)
                row["bodyparts3d"].append(bp)
                if bp["source_membership"] == "conflicting":
                    row.update(status="CONFLICT")
                    row["usable"]["group_plot"] = False
                    if row["group"]:
                        raise ValueError("reviewed primary mapping is in conflict")
                if not labels or row["status"] != ACCEPTED:
                    continue
                geometry = read_bounded(args.catalog.parent / "meshes" / mesh["filename"], 4 << 20)
                if digest(geometry) != mesh["sha256"]:
                    raise ValueError("BodyParts3D mesh digest differs")
                expected_name = f"{c['label']} [{mesh['fj_id']}]"
                moving_row = display_names.get(expected_name)
                if moving_row is None:
                    continue
                asset = display_asset(moving_row, source, source_blob, glb, rules, c, bp)
                asset.update(group_id=row["group"], part_actuator_id=row["id"] if labels[1] else None)
                assets.append(asset)
                row["display_assets"].append(asset["mesh_id"])
                row["usable"]["color"] = bool(labels[1])
        row["reason_codes"] = reasons + (["DISPLAY_LINK_REVIEWED"] if row["display_assets"] else
                                          ["NO_ACCEPTED_MOVING_SURFACE"])
        if proposal:
            row["reason_codes"].append("SIDED_CATALOG_LABEL")
        if row["status"] != ACCEPTED:
            row["reason_codes"].append({"UNMAPPED": "NO_SIDED_CATALOG_TARGET",
                                        "CANDIDATE": "EXACT_ANATOMY_REVIEW_PENDING",
                                        "CONFLICT": "IDENTITY_OR_ROUTE_CONFLICT",
                                        "NO_SOURCE_GEOMETRY": "NO_NATIVE_ROUTE"}[row["status"]])
        row["status_axes"] = {"native_path": "COMPILED_AND_RECORDED",
                              "anatomical_concept": ("REVIEWED_SIDED_GROUP" if row["group"] and not labels[1]
                                                      else row["status"]),
                              "display_asset": "LINKED" if row["display_assets"] else "NO_SOURCE_GEOMETRY",
                              "registration": "ILLUSTRATIVE" if row["display_assets"] else "NOT_EVALUATED",
                              "deformation": "NOT_VERIFIED"}
    for r in rows:
        if r["status"] == "CONFLICT":
            for membership in r["concept_membership"]:
                membership["status"] = "CONFLICT"

    state_match = all(i == f["state_index"] and times[i] == f["frame_time"] and
                      digest(states[i].tobytes()) == f["state_sha256"] for i, f in enumerate(motion["frames"]))
    if len(times) != len(motion["frames"]) or not state_match:
        raise ValueError("state binding differs")
    checked = check_moments(model, data, states, spec, [r for r in rows if r["group"]])
    accepted = [c["fma_id"] for r in rows for c in r["concept_membership"] if c["status"] == ACCEPTED]
    moving = [{"display_copy": r["node"], "name": r["name"], "mesh_id": f"myosuite:{r['source_node']}",
               "source_node": r["source_node"], "side": mesh_index.get(r["fj_id"], {}).get("side", "unknown"),
               "fma_id": r["fma_id"], "fj_label": r["fj_id"], "deformation": r["mode"],
               "source_membership": r["crosswalk"], "geometry_sha256": r["source_mesh_sha256"],
               "dataset": "MyoSuite", "dataset_revision": rules["myosuite_revision"]}
              for r in display.values()]
    moving.extend({"display_copy": r["node"], "name": r["name"], "mesh_id": f"zanatomy:{r['node']}",
                   "dataset": "Z-Anatomy", "dataset_revision": "0a849e8acf7080f8da3251a926fbc160d2bc3f7a",
                   "side": {"r": "right", "l": "left"}[r["side"]], "target_sites": r["target_sites"],
                   "geometry_sha256": r["source_mesh_sha256"], "deformation": r["mode"]}
                  for r in coverage["z_anatomy_surfaces"])
    for asset in moving + assets:
        asset.update(registration="ILLUSTRATIVE", deformation_validation="NOT_VERIFIED",
                     motion_asset_sha256=motion["artifacts"]["motion.glb"]["sha256"])
    muscle_nodes = {i for i, n in enumerate(glb["nodes"]) if n.get("extras", {}).get("layer") == "MUSCLES"
                    and "mesh" in n}
    if muscle_nodes != {r["display_copy"] for r in moving}:
        raise ValueError("moving muscle node inventory differs from the pinned GLB")
    mesh_status = {a["fj_label"]: "LINKED_MOVING_DISPLAY" for a in assets}
    anatomy_meshes = {item["mesh_id"] for r in rows for item in r["bodyparts3d"]}
    mesh_inventory = [{**r, "actuator_relation": mesh_status.get(
        r["fj_id"], "CATALOG_CANDIDATE" if r["fj_id"] in anatomy_meshes else "NO_REVIEWED_ACTUATOR_RELATION")}
        for r in mesh_index.values()]
    result = {"schema_version": SCHEMA, "source_model_sha256": rules["model_sha256"],
              "coverage_revision": 2, "nomenclature_sha256": digest(NOMENCLATURE.read_bytes()),
              "model_source": {"revision": "98a70c569c4c1b6da467a20012f766ee1f8dc521",
                               "license": "Apache-2.0", "url": "https://github.com/LNSGroup/MS-Human-700"},
              "nomenclature_source": {k: table[k] for k in ("source", "revision", "license", "documentation")},
              "source_geometry_inventory": {"bodyparts3d": mesh_inventory, "myosuite": coverage["source_surfaces"],
                                            "z_anatomy": coverage["z_anatomy_surfaces"]},
              "source_result_sha256": digest(manifest_raw), "trajectory_sha256": motion["trajectory_sha256"],
              "motion_sha256": digest(motion_raw), "anatomy_revision": rules["catalog_sha256"],
              "anatomy_sources": {"primary": dataset, "membership": [s for s in catalog["sources"] if
                  s["id"] in ("bp3d_43_primary", "bp3d_43_components", "bp3d_43i_components")]},
              "review_rules_sha256": digest(args.rules.read_bytes()), "run_id": run["run_id"],
              "counts": {"rows_accounted_for": len(rows), "accepted_anatomical_mappings": len(accepted),
                         "accepted_sided_group_row_mappings": sum(r["group"] is not None for r in rows),
                         "unique_accepted_fma_parts": len(set(accepted)),
                         "linked_pilot_display_assets": sum(a["group_id"].split(":")[0] in
                                                            {"pectoralis_major", "triceps_brachii"} for a in assets),
                         "linked_display_assets": len(assets),
                         "accepted_part_display_assets": sum(a["part_actuator_id"] is not None for a in assets),
                         "coarse_groups": dict(Counter(r["coarse_group"] for r in rows)),
                         "statuses": dict(Counter(r["status"] for r in rows)),
                         "illustrative_motion_surfaces": len(moving), "verified_anatomical_deformations": 0},
              "groups": groups, "reviewed_display_assets": unique(assets, "display_copy"),
              "motion_display_assets": unique(moving, "display_copy"), "rows": rows,
              "moment_arm_check": {"definition": "internal dL/dq holding other source coordinates fixed",
                                   "max_error": max(x["absolute_error_m_per_rad"] for x in checked), "rows": checked}}
    args.output.write_bytes(canonical(result) + b"\n")
    print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("run", "catalog", "myo", "clip", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=Path(__file__).with_name("review_rules.json"))
    parser.add_argument("--myo-sim", type=Path,
                        default=Path("outputs/v08/atlas-expansion/sources/myo-sim"))
    build(parser.parse_args())
