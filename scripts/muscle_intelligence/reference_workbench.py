"""Compare geometric candidates on pinned bones and emit the pilot inspection receipt."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import mujoco as mj
import numpy as np
from pydantic import Field, FiniteFloat, model_validator

from anatomy_lab import canonical, digest, read_bounded
import landmark_geometry as geometry
from human_models_mcp.atlas import verify_asset
from human_models_mcp.atlas_registration import native_bone, nearest, rigid_fit
from human_models_mcp.scene_export import load_saved_run
from muscle_contract import MuscleModel, Sha
from registration_evidence import SCHEMA, MAX_REPORT
from registration_native import ANCHORS, BONES, geom_pose

HERE = Path(__file__).resolve().parent
AXES = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
HELD_OUT = (2, 3)
LANDMARKS = {
    "clavicle": ["sternal articular surface centre", "acromial articular surface centre",
                 "conoid tubercle apex", "trapezoid line midpoint"],
    "scapula": ["inferior angle", "root of scapular spine", "posterolateral angle of acromion",
                "glenoid centre", "acromial AC joint point"],
    "humerus": ["greater tubercle apex", "lesser tubercle apex", "medial epicondyle apex",
                "lateral epicondyle apex", "intertubercular groove proximal midpoint"],
    "sternum": ["jugular notch midpoint", "sternal angle midpoint"],
    "tibia": ["medial malleolus apex", "tibial tuberosity apex", "medial tibial plateau rim"],
    "fibula": ["fibular head apex", "lateral malleolus apex"],
    "calcaneus": ["posterior calcaneal tuberosity midpoint", "sustentaculum tali apex"],
}
REGIONS = {
    "PECM1": ("pectoralis major · clavicular part", "medial half of the clavicle", "crest of the greater tubercle", 141),
    "PECM2": ("pectoralis major · sternocostal part", "sternal periosteum and second to sixth costal cartilages", "crest of the greater tubercle", 142),
    "PECM3": ("pectoralis major · abdominal part", "upper anterior rectus sheath", "crest of the greater tubercle", 143),
    "SUBSC": ("subscapularis", "subscapular fossa", "lesser tubercle and upper crest", 183),
    "soleus": ("soleus", "posterior fibular head and proximal fibula, soleal line and medial tibial border", "calcaneal tuberosity via the Achilles tendon", 257),
}
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Point = tuple[Number, Number, Number]
Text = Annotated[str, Field(min_length=1, max_length=256)]


Weight = Annotated[Number, Field(ge=0, le=1)]


class Anchor(MuscleModel):
    face: int = Field(ge=0, strict=True)
    weights: tuple[Weight, Weight, Weight]


class Correspondence(MuscleModel):
    id: Text
    name: Text
    side: Literal["left", "right", "unknown"]
    source_fj_id: Annotated[str, Field(pattern=r"^FJ[0-9]+M?$")]
    source_sha256: Sha
    target_geom: Text
    target_mesh_sha256: Sha
    source_frame: Literal["BodyParts3D OBJ mm"]
    target_frame: Literal["MuJoCo geom-local m"]
    role: Literal["FIT", "HELD_OUT"]
    source_mm: Point | None = None
    target_geom_m: Point | None = None
    source_evidence: Text
    source_bp_id: str | None = None
    source_fma_id: str | None = None
    anatomy_revision: Sha | None = None
    source_model_sha256: Sha | None = None
    geometry_sha256: Sha | None = None
    source_anchor: Anchor | None = None
    target_anchor: Anchor | None = None
    method: Literal["OPERATOR_SURFACE_PICK"] | None = None
    evidence_sha256: Sha | None = None
    uncertainty_mm: Annotated[FiniteFloat, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def coordinates(self):
        if (self.source_mm is None) != (self.target_geom_m is None):
            raise ValueError("coordinate pair must be complete")
        return self


class Decision(MuscleModel):
    id: Text
    correspondence_id: Text
    reviewer: Text
    evidence: Text
    decision: Literal["USE_FOR_COMPARISON", "REJECT", "WITHDRAW"]
    supersedes: Text | None = None
    time: datetime | None = None


class Footprint(MuscleModel):
    pilot_node: int = Field(strict=True, ge=0, le=4095)
    region: Literal["origin", "insertion"]
    reviewer: Text
    evidence: Text
    source_fj_id: Annotated[str, Field(pattern=r"^FJ[0-9]+M?$")]
    source_sha256: Sha
    source_frame: Literal["BodyParts3D OBJ mm"]
    polygon_mm: list[Point] = Field(min_length=3, max_length=64)


def source_citation(value):
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname and not parsed.username and not any(
        char.isspace() for char in value)


class AnnotationLog(MuscleModel):
    schema_version: Literal["hmm.registration-annotations/1", "hmm.registration-annotations/2"]
    correspondences: list[Correspondence] = Field(max_length=300)
    decisions: list[Decision] = Field(max_length=600)
    footprints: list[Footprint] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def history(self):
        items = {item.id: item for item in self.correspondences}
        if len(items) != len(self.correspondences):
            raise ValueError("duplicate correspondence ID")
        latest, used = {}, set()
        for entry in self.decisions:
            if (entry.id in used or entry.correspondence_id not in items
                    or entry.supersedes != latest.get(entry.correspondence_id)):
                raise ValueError("invalid correspondence decision history")
            if entry.decision == "USE_FOR_COMPARISON" and items[entry.correspondence_id].source_mm is None:
                raise ValueError("comparison decision requires both coordinates")
            latest[entry.correspondence_id] = entry.id
            used.add(entry.id)
            if self.schema_version.endswith("/2") and (
                entry.time is None or entry.time.utcoffset() is None or not entry.reviewer.strip()
                or not entry.evidence.strip()
            ):
                raise ValueError("decision needs time zone, reviewer and evidence")
        if self.schema_version.endswith("/2"):
            if self.footprints:
                raise ValueError("named-landmark editing does not accept footprints")
            for item in self.correspondences:
                if item.source_mm is not None and (
                    item.id not in latest or item.method is None or item.uncertainty_mm is None
                    or not source_citation(item.source_evidence)
                    or item.source_anchor is None or item.target_anchor is None
                ):
                    raise ValueError("placed point requires pinned anchors, HTTPS citation, uncertainty and decision")
        return self


def pinned_annotations(log, pair, mesh, landmark_names):
    if not log:
        return []
    decisions = {entry.correspondence_id: entry for entry in log.decisions}
    selected = []
    for item in log.correspondences:
        if (item.source_fj_id, item.target_geom) != (pair["source_fj_id"], pair["target_geom"]):
            continue
        if log.schema_version.endswith("/1") and item.source_mm is None:
            continue
        if any(getattr(item, key) != value for key, value in pair.items()) or item.name not in landmark_names:
            raise ValueError("annotation identity, side, revision or frame differs")
        if item.source_mm is None:
            continue
        if mesh is None or log.schema_version.endswith("/1"):
            raise ValueError("coordinate-bearing annotations require v2 shoulder mesh anchors")
        geometry.check_anchor(mesh["source"], item.source_mm, item.source_anchor, 1)
        geometry.check_anchor(mesh["target"], item.target_geom_m, item.target_anchor, 1000)
        if decisions[item.id].decision == "USE_FOR_COMPARISON":
            if any(item.name == other.name
                   or np.linalg.norm(np.subtract(item.source_mm, other.source_mm)) <= geometry.TOLERANCE_MM
                   or np.linalg.norm(np.subtract(item.target_geom_m, other.target_geom_m)) * 1000
                   <= geometry.TOLERANCE_MM for other in selected):
                raise ValueError("duplicate active name or coordinates, including fit/held-out leakage")
            selected.append(item)
    fit = [item for item in selected if item.role == "FIT"]
    if len(fit) >= 3:
        rigid_fit(np.asarray([item.source_mm for item in fit]), np.asarray([item.target_geom_m for item in fit]))
    return [{"status": "OPERATOR_CANDIDATE", **item.model_dump(mode="json"),
             "decision": decisions[item.id].model_dump(mode="json")} for item in selected]


def sample_indices(n, maximum):
    return np.linspace(0, n - 1, min(n, maximum), dtype=int)


def extremes(points):
    return [int(f(points[:, axis])) for axis in range(3) for f in (np.argmin, np.argmax)]


def apply(transform, points):
    return np.asarray(points) @ transform[:3, :3].T + transform[:3, 3]


def matrix(rotation, offset):
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation.T, offset
    return transform


def rms_mm(values):
    return float(np.sqrt(np.mean(np.square(values))) * 1000)


def compare(source, target, source_raw, basis, neutral_to_local, archived, annotations):
    si, ti = extremes(source), extremes(target)
    held = list(HELD_OUT)
    train = [i for i in range(6) if i not in held and si[i] not in {si[j] for j in held}
             and ti[i] not in {ti[j] for j in held}]
    s, t = source[si], target[ti]
    # Both ICP input clouds exclude the evaluator vertices on their respective meshes.
    ss = np.delete(source, sorted({si[i] for i in held}), axis=0)
    tt = np.delete(target, sorted({ti[i] for i in held}), axis=0)
    rotation, offset = np.eye(3), tt.mean(0) - ss.mean(0)
    for _ in range(25):
        paired, distances = nearest(tt, ss @ rotation + offset)
        keep = distances <= np.quantile(distances, .9)
        rotation, offset = rigid_fit(ss[paired[keep]], tt[keep])
    conversion = matrix(basis.T / 1000, np.zeros(3))

    def metrics(transform, fitted_source, fitted_target, scored_source, scored_target):
        aligned = apply(transform, source)
        return {
            "source_mm_to_target_geom_m": (neutral_to_local @ transform @ conversion).tolist(),
            "rotation_det": float(np.linalg.det(transform[:3, :3])),
            "fit_marker_count": len(fitted_source),
            "fit_marker_rms_mm": rms_mm(np.linalg.norm(apply(transform, fitted_source) - fitted_target, axis=1))
            if len(fitted_source) else None,
            "held_out_count": len(scored_source),
            "held_out_rms_mm": rms_mm(np.linalg.norm(apply(transform, scored_source) - scored_target, axis=1)),
            "held_out_residuals_mm": (np.linalg.norm(apply(transform, scored_source) - scored_target, axis=1) * 1000).tolist(),
            "held_out_max_mm": float(np.linalg.norm(apply(transform, scored_source) - scored_target, axis=1).max() * 1000),
            "source_to_target_vertex_rms_mm": rms_mm(nearest(target, aligned)[1]),
            "target_to_source_vertex_rms_mm": rms_mm(nearest(aligned, target)[1]),
        }

    methods = {"icp_held_out": metrics(matrix(rotation, offset), [], [], s[held], t[held])}
    try:
        methods["axis_extrema_rigid"] = metrics(matrix(*rigid_fit(s[train], t[train])), s[train], t[train],
                                                s[held], t[held])
    except ValueError as exc:
        methods["axis_extrema_rigid"] = {"status": "INCONCLUSIVE", "reason": str(exc)}
    markers = [{"name": name, "status": "CANDIDATE", "method": "GEOMETRIC_PROXY", "target_status": "MODEL_INTERNAL",
                "role": "HELD_OUT" if i in held else "FIT" if i in train else "EXCLUDED_DUPLICATE",
                "source_mm": source_raw[si[i]].tolist(), "target_geom_m": apply(neutral_to_local, t[i]).tolist()}
               for i, name in enumerate(AXES)]
    manual = {"status": "NOT_RUN", "reason": "NO_REVIEWED_NONDEGENERATE_FIT_AND_HELD_OUT_PAIRS"}
    groups = {role: [item for item in annotations if item.role == role] for role in ("FIT", "HELD_OUT")}
    if len(groups["FIT"]) >= 3 and groups["HELD_OUT"]:
        fit, scored = groups["FIT"], groups["HELD_OUT"]
        a, b = [[np.asarray([item.source_mm for item in group]) @ basis.T / 1000,
                 apply(np.linalg.inv(neutral_to_local), [item.target_geom_m for item in group])]
                for group in (fit, scored)]
        if (set(item.source_mm for item in fit) & set(item.source_mm for item in scored)
                or set(item.target_geom_m for item in fit) & set(item.target_geom_m for item in scored)):
            raise ValueError("manual fit and held-out coordinates overlap")
        try:
            manual = {"status": "CANDIDATE", "fit_ids": [item.id for item in fit],
                      "held_out_ids": [item.id for item in scored],
                      **metrics(matrix(*rigid_fit(*a)), *a, *b)}
        except ValueError as exc:
            manual = {"status": "INCONCLUSIVE", "reason": str(exc)}
    local = np.asarray(archived["source_mm_to_native_geom_m"])
    return {
        "methods": methods, "manual_named_landmark_rigid": manual, "markers": markers,
        "sample_counts": {"source": len(source), "target": len(target),
                          "held_out_icp_fit_source": len(ss), "held_out_icp_fit_target": len(tt)},
        "atlas_preview_geom_m": apply(local, source_raw[sample_indices(len(source_raw), 96)]).tolist(),
    }


def write(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def build(args):
    pinned = (
        (args.base / "ANATOMICAL_REGISTRATION_QA.json", args.qa_sha256),
        (args.base / "CROSSWALK_V3.json", args.crosswalk_sha256),
    )
    inputs = []
    for path, expected in pinned:
        raw = read_bounded(path, 8 << 20)
        if digest(raw) != expected:
            raise ValueError(f"baseline receipt differs: {path.name}")
        inputs.append(json.loads(raw))
    qa, mapping = inputs
    manifest_raw, motion_raw, catalog_raw = [(p.read_bytes()) for p in
        (args.run / "manifest.json", args.clip / "motion.json", args.catalog)]
    motion, catalog, manifest = map(json.loads, (motion_raw, catalog_raw, manifest_raw))
    pins = {"run_id": manifest["run_id"], "source_result_sha256": digest(manifest_raw),
            "motion_sha256": digest(motion_raw), "anatomy_revision": digest(catalog_raw),
            "source_model_sha256": manifest["model"]["asset_sha256"]}
    if (any(mapping[key] != value for key, value in pins.items())
            or qa["run_id"] != pins["run_id"] or qa["motion_sha256"] != pins["motion_sha256"]
            or qa["mapping_revision_sha256"] != args.crosswalk_sha256
            or qa["clock_s"] != [f["frame_time"] for f in motion["frames"]]
            or qa["anchors"] != list(ANCHORS)):
        raise ValueError("baseline receipts bind to different scientific inputs")
    coverage_raw = (args.clip / "coverage.json").read_bytes()
    if (digest(coverage_raw) != motion["artifacts"]["coverage.json"]["sha256"]
            or json.loads(coverage_raw)["native_bones"] != qa["native_bones"]):
        raise ValueError("native bone inventory differs")
    for file in ("trajectory.npz", "model_recipe.json"):
        if digest((args.run / file).read_bytes()) != manifest["artifacts"][file]["sha256"]:
            raise ValueError(f"saved run artifact differs: {file}")
    _, model, _, _, _, _, _, _, _, _ = load_saved_run(args.run)
    neutral = mj.MjData(model)
    mj.mj_forward(model, neutral)
    inventory = {row["fj_id"]: row for row in catalog["meshes"]}
    native = {row["name"]: row for row in qa["native_bones"]}
    basis = np.asarray(qa["frame_basis"]["bodyparts3d_to_native_basis"]["world_basis"])
    if not np.allclose(basis @ basis.T, np.eye(3)) or np.linalg.det(basis) != 1:
        raise ValueError("invalid basis conversion")
    sources = json.loads((HERE / "reference_sources.json").read_bytes())
    annotation_raw = read_bounded(args.annotations, 1 << 20) if args.annotations else None
    log = AnnotationLog.model_validate_json(annotation_raw) if annotation_raw else None
    expected_pairs, bones = {}, {}
    args.output.mkdir(exist_ok=True)
    mesh_dir = args.output / "landmark-mesh"
    mesh_dir.mkdir()
    template = {"schema_version": "hmm.registration-annotations/2", "correspondences": [], "decisions": [], "footprints": []}
    for name, bone in qa["bone_fits"].items():
        label = BONES[name]
        side = label.split()[0] if " " in label else "unknown"
        structure = label.removeprefix(f"{side} ")
        item = {k: v for k, v in bone.items() if k != "alternatives"}
        bones[name] = {**item, "side": side, "native": native.get(name),
                       "named_landmarks": [{"name": x, "status": "NOT_VERIFIED", "source_mm": None,
                                            "target_geom_m": None} for x in LANDMARKS[structure]],
                       "alternatives": []}
        for candidate in bone.get("alternatives", []):
            fj = candidate["fj_id"]
            row = inventory[fj]
            target_identity = native[name]
            source_path = args.catalog.parent / "meshes" / row["filename"]
            verify_asset(source_path, row)
            if (row["sha256"] != candidate["source_sha256"] or candidate["side"] != side
                    or row["side"] != side or row["identity_status"] != "MATCH"
                    or row["label"].lower() != label.lower()
                    or candidate["geom_id"] != target_identity["geom_id"]):
                raise ValueError("bone identity or laterality differs")
            pair = {"source_fj_id": fj, "source_sha256": row["sha256"], "target_geom": name,
                    "target_mesh_sha256": target_identity["source_mesh_sha256"], "side": side,
                    "source_frame": "BodyParts3D OBJ mm", "target_frame": "MuJoCo geom-local m"}
            mesh = None
            geometry_ref = {}
            if structure in {"clavicle", "scapula", "humerus"}:
                geometry.validate_transform(candidate["source_mm_to_native_geom_m"])
                mesh = {"source": geometry.obj(source_path), "target": geometry.native(model, name)}
                payload = canonical(mesh)
                if len(payload) > geometry.MAX_GEOMETRY:
                    raise ValueError("landmark mesh exceeds publication bound")
                sha = digest(payload)
                asset = mesh_dir / f"{sha}.json"
                if not asset.exists():
                    asset.write_bytes(payload)
                pair.update(source_bp_id=row["bp_id"], source_fma_id=row["obj_concept_id"],
                            anatomy_revision=pins["anatomy_revision"], source_model_sha256=pins["source_model_sha256"],
                            geometry_sha256=sha)
                geometry_ref = {"geometry": {"sha256": sha, "bytes": len(payload),
                                "tolerance_mm": geometry.TOLERANCE_MM,
                                "source_revision": sources["sources"][0]["version"],
                                "source_citation": sources["sources"][0]["url"],
                                "target_revision": sources["sources"][1]["version"]}}
                for j, landmark in enumerate(LANDMARKS[structure]):
                    template["correspondences"].append({"id": f"{fj}/{name}/{j}", "name": landmark, **pair,
                        "role": "FIT" if j < 3 else "HELD_OUT", "source_evidence": sources["sources"][0]["url"],
                        "source_mm": None, "target_geom_m": None})
            expected_pairs[(fj, name)] = pair
            annotations = pinned_annotations(log, pair, mesh, LANDMARKS[structure])
            selected = [Correspondence.model_validate({k: v for k, v in item.items()
                        if k not in {"status", "decision"}}) for item in annotations]
            raw = np.asarray([[float(v) for v in line.split()[1:4]] for line in source_path.read_text(encoding="utf-8").splitlines()
                              if line.startswith("v ")])
            target = native_bone(model, neutral, name)
            source_sample = raw[sample_indices(len(raw), 1200)]
            target_sample = target[sample_indices(len(target), 1200)]
            measured = compare(source_sample @ basis.T / 1000, target_sample, source_sample, basis,
                               np.linalg.inv(geom_pose(neutral, candidate["geom_id"])), candidate, selected)
            bones[name]["alternatives"].append({"status": "CANDIDATE", "source_id": row["source_id"],
                "source_fma_id": row["obj_concept_id"], "source_bp_id": row["bp_id"], **pair,
                "archived_icp": candidate, "annotations": annotations, **geometry_ref, **measured})
        if bone.get("alternatives"):
            bones[name]["status"] = "CANDIDATE"
    if log and any((c.source_fj_id, c.target_geom) not in expected_pairs for c in log.correspondences):
        raise ValueError("annotation refers to a bone pair outside the measured pilot")

    pilots, routes = {}, {}
    for node, pilot in qa["pilot_surfaces"].items():
        route = pilot["route_control"]
        side = pilot["side"]
        suffix = side[0]
        mirror = "_mirror" if side == "left" else ""
        family = route.rsplit("_", 1)[0] if route else None
        if family == "soleus":
            region_bones = [f"{suffix}_{bone}" for bone in ("tibia", "fibula", "foot")]
        else:
            region_bones = [f"{bone}{mirror}" for bone in ("clavicle", "scapula", "humerus")] if route else []
            if family in {"PECM2", "PECM3"}:
                region_bones.append("Sternum")
        meta = inventory.get(pilot["fj_label"])
        exact = mapping["reviewed_display_assets"].get(node, {}).get("part_actuator_id")
        item = {"node": int(node), "side": side, "display_name": pilot["name"], "bones": region_bones,
                "native_route": route, "native_route_status": "MODEL_INTERNAL" if route else "NOT_VERIFIED",
                "visual_surface": {k: pilot[k] for k in ("dataset", "dataset_revision", "mesh_id", "geometry_sha256")},
                "atlas_surface": {"fj_id": meta["fj_id"], "fma_id": meta["obj_concept_id"], "sha256": meta["sha256"],
                                  "source_id": meta["source_id"], "status": "SOURCE"} if meta else None,
                "association": "REVIEWED_ANATOMICAL" if exact is not None else "REVIEWED_GROUP_ONLY" if route else "GEOMETRY_ONLY",
                "attachment_status": "NOT_VERIFIED", "candidate_footprints": []}
        if route:
            label, origin, insertion, row = REGIONS[family]
            samples = qa["routes"][route]["samples"]
            item["textual_reference"] = {"source_id": "bp3d_attachment_workbook", "list_row": row, "status": "SOURCE",
                                         "label": label, "origin_region": origin, "insertion_region": insertion,
                                         "coordinate_status": "NOT_VERIFIED", "identity_link": "CANDIDATE"}
            if len(samples) != len(motion["frames"]) or any(
                (entry["state_index"], entry["time_s"]) != (frame["state_index"], frame["frame_time"])
                for entry, frame in zip(samples, motion["frames"], strict=True)
            ):
                raise ValueError("native route samples bind to a different frame")
            xyz = np.asarray([entry["model_sites_world_m"] for entry in samples])
            item["max_consecutive_site_displacement_mm"] = float(np.linalg.norm(np.diff(xyz, axis=0), axis=2).max() * 1000)
            routes[route] = {"samples": [{k: s[k] for k in ("state_index", "time_s", "model_sites_world_m",
                         "wrap_polyline_world_m", "wrap_object_id", "native_length_m")} for s in samples]}
        pilots[node] = item
    for footprint in log.footprints if log else ():
        pilot = pilots.get(str(footprint.pilot_node))
        choices = [pair for pair in expected_pairs.values() if pair["source_fj_id"] == footprint.source_fj_id
                   and pair["source_sha256"] == footprint.source_sha256 and pilot
                   and pair["target_geom"] in pilot["bones"]]
        if len(choices) != 1 or pilot["association"] == "GEOMETRY_ONLY":
            raise ValueError("footprint source is not a pinned bone of this pilot")
        xyz = np.asarray(footprint.polygon_mm)
        if len(np.unique(xyz, axis=0)) != len(xyz) or np.linalg.matrix_rank(xyz - xyz.mean(0)) < 2:
            raise ValueError("degenerate candidate footprint")
        pilot["candidate_footprints"].append({"status": "CANDIDATE", **footprint.model_dump(mode="json")})
    blockers = [
        {"id": "INDEPENDENT_BONE_CORRESPONDENCES", "status": "NOT_VERIFIED",
         "missing": "Compatible measured named landmarks with known geometry, subject, frame and held-out points."},
        {"id": "ATTACHMENT_FOOTPRINTS", "status": "NOT_VERIFIED",
         "missing": "Licensed measured origin and insertion areas paired to the source and target bones."},
        {"id": "FEM", "status": "NOT_RUN",
         "missing": "Verified closed oriented volume mesh, fibres, material and attachment boundary evidence."},
    ]
    report = {"schema_version": SCHEMA, **pins,
              "claims": {"source_provenance": "PINNED", "geometry_fit": "CANDIDATE",
                         "expert_review": "PENDING", "attachment_footprint": "NOT_VERIFIED",
                         "human_physiology": "NOT_VALIDATED"}, "mapping_revision_sha256": args.crosswalk_sha256,
              "baseline_qa_sha256": args.qa_sha256, "annotation_sha256": digest(annotation_raw) if annotation_raw else None,
              "frames": motion["frames"], "sources": sources, "bones": bones, "pilots": pilots, "routes": routes,
              "blockers": blockers, "independent_landmarks": {"status": "NOT_VERIFIED", "count": 0},
              "anatomical_registration": "NOT_VERIFIED", "biological_deformation": "NOT_RUN",
              "comparison_decision": "INCONCLUSIVE", "accepted_deformation": "LBS"}
    args.output.mkdir(exist_ok=True)
    receipt = args.output / "REGISTRATION_INSPECTION_QA.json"
    write(receipt, report)
    raw_receipt = read_bounded(receipt, MAX_REPORT)
    (args.output / "registration-evidence.sha256").write_text(digest(raw_receipt) + "\n", encoding="utf-8", newline="\n")
    write(args.output / "REFERENCE_SOURCE_MATRIX.json", sources)
    write(args.output / "LANDMARK_AND_CORRESPONDENCE.json", template)
    write(args.output / "ATTACHMENT_EVIDENCE.json", {"pilots": pilots, "blockers": blockers})
    write(args.output / "MAPPING_DECISIONS.json", log.model_dump(mode="json") if log else
          {"schema_version": template["schema_version"], "correspondences": [], "decisions": [], "footprints": []})
    write(args.output / "BONE_REGISTRATION_BENCHMARK.json", {"bones": bones, "comparison_decision": "INCONCLUSIVE",
          "independent_landmarks": report["independent_landmarks"], "units": "mm",
          "sampling": "Up to 1200 evenly indexed vertices per cloud. Axis-extreme vertex proxies in converted qpos0 frame. "
          "Both ICP inputs exclude two held-out vertices per cloud unless the two axes share a vertex. "
          "Vertex distances are bidirectional nearest-neighbour RMS. Archived ICP used its full sample."})
    print("Pilots", len(pilots), "states", len(motion["frames"]), "bone candidates",
          sum(len(bone["alternatives"]) for bone in bones.values()),
          "mapping", dict(Counter(row["status"] for row in mapping["rows"])),
          "registration NOT_VERIFIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "run", "clip", "catalog", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("qa-sha256", "crosswalk-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--annotations", type=Path)
    build(parser.parse_args())
