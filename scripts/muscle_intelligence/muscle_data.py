"""Verified, bounded reads of recorded native signals for one installed MotionScene."""

from human_models_mcp.runtime.locking import file_lock
from functools import lru_cache
from io import BytesIO
import json
from math import prod
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile

import numpy as np

from anatomy_lab import canonical, digest, read_bounded
from human_models_mcp.results import error
from human_models_mcp.scene_export import safe_archive
from human_models_mcp.scientific_quantity import DERIVED, MUSCLE, scientific_quantity, sources
from muscle_contract import MuscleRegistration, MuscleSearch, MuscleSeries, MuscleSelect, MuscleSelection
from registration_evidence import at_frame, load_evidence

UNITS = {name: row["unit"] for name, row in MUSCLE.items()
         if name not in ("overlay", "display_surface", "full_integrator_work_J")}
LIMITATIONS = (
    "Model activation is a dimensionless actuator state, distinct from surface EMG. "
    "Signed MuJoCo transmission force generally uses negative values for tension. "
    "Path length, velocity and power describe transmissions. Surface color is uniform per displayed piece. "
    "Display meshes use illustrative registration. Tissue stress and external human validation are unavailable."
)
RAW_METRICS = tuple(k for k in UNITS if k not in ("force_magnitude_N", "work_J"))
MOMENT_FIELDS = ("moment_values", "moment_columns", "moment_rowadr", "moment_rownnz")
GROUP_DEFINITIONS = {
    "arithmetic_mean_of_paths": "Arithmetic mean over the reviewed group's paths at each saved sample.",
    "sum_of_signed_path_forces": "Scalar sum of signed transmission forces. A net anatomical force requires vector directions and points of application.",
    "sum_of_absolute_path_forces": "Sum of the absolute scalar forces over the group's paths at each saved sample.",
    "sum_of_signed_path_powers": "Sum of signed force times signed path velocity over the group's paths at each saved sample.",
    "sum_of_signed_path_work": "Sum of cumulative sampled work over the group's paths at each saved sample.",
}


def verified_bytes(root, manifest, name, limit):
    raw = read_bounded(root / name, limit)
    expected = manifest["artifacts"][name]
    if len(raw) != expected["bytes"] or digest(raw) != expected["sha256"]:
        raise ValueError(f"source artifact SHA-256 or length differs: {name}")
    return raw


@lru_cache(maxsize=8)
def arrays(raw, fields):
    """The cache key contains the SHA-verified compressed bytes; a changed file cannot hit."""
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if (sorted(item.filename for item in members) != sorted(f"{name}.npy" for name in fields)
                    or sum(item.file_size for item in members) > 8 << 20
                    or any(item.flag_bits & 1 for item in members)):
                raise ValueError("unexpected, duplicate, encrypted or oversized NPZ member")
            for item in members:
                with archive.open(item) as stream:
                    version = np.lib.format.read_magic(stream)
                    header = {(1, 0): np.lib.format.read_array_header_1_0,
                              (2, 0): np.lib.format.read_array_header_2_0}.get(version)
                    if header is None:
                        raise ValueError("unsupported NPY header version")
                    shape, _, dtype = header(stream)
                    if (dtype.kind not in "fiu" or any(d < 0 for d in shape)
                            or prod(shape) * dtype.itemsize != item.file_size - stream.tell()):
                        raise ValueError("NPY payload size or dtype differs from header")
        safe_archive(BytesIO(raw))
        with np.load(BytesIO(raw), allow_pickle=False) as pack:
            data = {key: pack[key] for key in fields}
        if any(v.dtype.kind not in "fiu" or not np.isfinite(v).all() for v in data.values()):
            raise ValueError("nonfinite or unsupported NPZ data")
        for value in data.values():
            value.flags.writeable = False
        return data
    except (BadZipFile, EOFError, OverflowError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("corrupt or unsupported NPZ") from exc


def derived(metric, values):
    if metric in ("activation", "excitation"):
        return "arithmetic_mean_of_paths", values.mean(axis=1)
    if metric in ("force_N", "force_magnitude_N", "power_W", "work_J"):
        label = {"force_N": "sum_of_signed_path_forces", "force_magnitude_N": "sum_of_absolute_path_forces",
                 "power_W": "sum_of_signed_path_powers", "work_J": "sum_of_signed_path_work"}[metric]
        return label, values.sum(axis=1)
    return None, None


def activation_color(value):
    """Linear RGB endpoints, shared with Three and Blender through the selection receipt."""
    a = min(1.0, max(0.0, value))
    return [0.025 + 0.955 * a, 0.15 + 0.57 * a, 0.55 - 0.485 * a]


def signal_identity(row):
    status = {"REVIEWED_ANATOMICAL": "accepted", "CANDIDATE": "candidate", "CONFLICT": "conflict"}
    return {"actuator_id": row["id"], "exact_name": row["exact_name"], "side": row["side"],
            "mapping_status": status.get(row["status"], "unmapped"),
            "actuator_to_group": {"id": row["group"], "status": "REVIEWED" if row["group"] else "UNMAPPED"},
            "anatomical_scope": row.get("status_axes", {}).get("anatomical_concept", row["status"]),
            "fma": [{"id": c["fma_id"], "status": status.get(c["status"], "unmapped"), "source": c["source"]}
                    for c in row["concept_membership"]],
            "display_assets": row["display_assets"], "registration": "ILLUSTRATIVE" if row["display_assets"] else None,
            "source_xml_sha256": row.get("registration_review", {}).get("model_xml_sha256")}


def signal_evidence(context, metric, files, window=None, asset=None, group=None, available=True):
    _, mapping, _, run, base = context
    return {**scientific_quantity(run, {metric: {**MUSCLE[metric],
                                               "availability": "AVAILABLE" if available else "NO_DATA"}},
                                  files=files, window=window,
                                  uncertainty=("Source muscle force parameters and recruitment are uncalibrated for this run.",
                                               "The controller and support model affect the computed values.",
                                               "Display registration and deformation are illustrative.")),
            "source_manifest_sha256": base["source_result_sha256"],
            "mapping_revision_sha256": base["mapping_revision_sha256"], "motion_sha256": base["motion_sha256"],
            "crosswalk": {"revision": base["crosswalk_revision"], "catalog_sha256": base["anatomy_revision"],
                          "review_rules_sha256": mapping.get("review_rules_sha256"),
                          "group_to_fma": ({"group_id": group["group_id"], "fma_id": group.get("parent_fma_id"),
                                            "status": "REVIEWED_SIDED_GROUP" if group.get("parent_fma_id")
                                            else "UNMAPPED"} if group else None)},
            "display_identity": ({"node": asset["display_copy"], "geometry_sha256": asset.get("geometry_sha256"),
                                  "dataset": asset["dataset"], "fma_id": asset.get("fma_id"),
                                  "dataset_revision": asset.get("dataset_revision"),
                                  "fma_to_geometry": {"source_membership": asset.get("source_membership"),
                                                      "registration": asset.get("registration"),
                                                      "deformation": asset.get("deformation"),
                                                      "deformation_validation": asset.get("deformation_validation")},
                                  "fma_scope": "source_geometry",
                                  "native_association": ("reviewed_part" if asset.get("part_actuator_id") is not None
                                                         else "reviewed_sided_group" if asset.get("group_id") else None),
                                  "mapping_status": "accepted" if asset.get("group_id") else "geometry_only"}
                                 if asset else None),
            "independent_check": "Check saved actuator arrays and the model route. Human validation needs a separately measured "
                                 "observable and protocol. EMG can inform activation timing under a defined protocol."}


class MuscleData:
    def __init__(self, whole, path, sha, selection_path=None):
        self.whole = whole
        self.path = Path(path)
        self.sha = sha
        self.selection_path = Path(selection_path) if selection_path else None
        self.evidence_path = os.environ.get("HMM_LAB_REGISTRATION_EVIDENCE")
        self.evidence_sha = os.environ.get("HMM_LAB_REGISTRATION_EVIDENCE_SHA")

    @lru_cache(maxsize=2)
    def mapping(self, raw):
        if digest(raw) != self.sha:
            raise ValueError("crosswalk SHA-256 differs")
        result = json.loads(raw)
        rows = result["rows"]
        if (result["schema_version"] != "hmm.muscle.crosswalk/1" or len(rows) != 700
                or result.get("coverage_revision", 1) not in (1, 2, 3)
                or [r["id"] for r in rows] != list(range(700))
                or len({r["exact_name"] for r in rows}) != 700
                or len({r["tendon_id"] for r in rows}) != 700):
            raise ValueError("invalid compiled crosswalk inventory")
        return result

    def context(self, run_id, scene=None):
        scene = scene or self.whole.verified()
        if str(run_id) != scene["run_id"]:
            raise LookupError("no signals for that installed run")
        mapping = self.mapping(read_bounded(self.path, 8 << 20))
        root = self.whole.run_root / scene["run_id"]
        manifest_raw = read_bounded(root / "manifest.json", 1 << 20)
        if digest(manifest_raw) != scene["source_manifest_sha256"]:
            raise ValueError("source manifest changed during binding")
        manifest = json.loads(manifest_raw)
        acceptance = manifest["scientific"]["acceptance"]
        model_sha = manifest["model"]["asset_sha256"]
        if (mapping["run_id"] != scene["run_id"] or scene["run_id"] != manifest["run_id"]
                or mapping["source_model_sha256"] != model_sha or model_sha != scene["model"]["asset_sha256"]
                or mapping["source_result_sha256"] != scene["source_manifest_sha256"]
                or mapping["trajectory_sha256"] != scene["trajectory_sha256"]
                or mapping["anatomy_revision"] != scene["catalog_sha256"]
                or mapping["motion_sha256"] != self.whole.sha
                or scene["acceptance"] != acceptance or scene["human_validation"] != acceptance["human_experimental_validation"]
                or scene["control"] != manifest["execution"]["parameters"]["control"]):
            raise ValueError("run, model, anatomy, motion or acceptance binding differs")
        base = {"status": "ok", "schema_version": "hmm.muscle/1", "run_id": scene["run_id"],
                "source_model_sha256": model_sha, "source_result_sha256": mapping["source_result_sha256"],
                "mapping_revision_sha256": self.sha, "crosswalk_revision": mapping.get("coverage_revision", 1),
                "anatomy_revision": mapping["anatomy_revision"],
                "motion_sha256": self.whole.sha, "control": scene["control"], "acceptance": acceptance,
                "human_validation": scene["human_validation"], "metric": None, "unit": None,
                "limitations": LIMITATIONS}
        return scene, mapping, root, manifest, base

    def series(self, context, metric, ids, group_id=None, start_s=None, end_s=None,
               offset=0, limit=120, stride=1, phase_summary=False):
        scene, mapping, root, manifest, base = context
        base = {**base, "metric": metric, "unit": UNITS[metric]}
        group = mapping["groups"].get(group_id)
        if group_id:
            if group is None:
                return {**base, "mapping_status": "UNMAPPED", "data_status": "NO_DATA", "series": []}
            ids = group["actuator_ids"]
        rows = mapping["rows"]
        if any(i >= len(rows) for i in ids):
            return {**base, "mapping_status": "UNMAPPED", "data_status": "NO_DATA", "series": []}
        frames = scene["frames"]
        if not 3 <= len(frames) <= 401 or [f["state_index"] for f in frames] != list(range(len(frames))):
            raise ValueError("invalid saved state indices")
        clock = np.asarray([f["frame_time"] for f in frames])
        if not np.isfinite(clock).all() or not np.all(np.diff(clock) > 0):
            raise ValueError("invalid saved state clock")
        raw = verified_bytes(root, manifest, "trajectory.npz", 8 << 20)
        trajectory = arrays(raw, ("states", "state_spec", "time_s", "qpos"))
        if not np.array_equal(trajectory["time_s"], clock):
            raise ValueError("trajectory and scene clocks differ")
        lo = clock[0] if start_s is None else start_s
        hi = clock[-1] if end_s is None else end_s
        if not clock[0] <= lo <= hi <= clock[-1]:
            raise ValueError("time window lies outside saved states")
        metadata = json.loads(verified_bytes(root, manifest, "trajectory_metadata.json", 128 << 10))
        source = json.loads(verified_bytes(root, manifest, "actuators.json", 1 << 20))["actuators"]
        expected = [(r["id"], r["exact_name"], r["tendon_id"], r["source_actadr"]) for r in rows]
        if ([(r["id"], r["name"], r["tendon_id"], r["actadr"]) for r in source] != expected
                or metadata["actuator_order"] != [r["exact_name"] for r in rows]
                or any(metadata["units"].get(k) != UNITS[k] for k in RAW_METRICS)):
            raise ValueError("actuator order, names, tendon IDs or units differ")
        names = manifest["outputs"]["muscles"]["chunks"]
        if (not 1 <= len(names) <= 32 or metadata["muscle_chunks"] != names
                or names != [f"muscles_{i:03d}.npz" for i in range(len(names))]):
            raise ValueError("invalid or missing declared muscle chunks")
        series, index = [], 0
        for name in names:
            chunk = arrays(verified_bytes(root, manifest, name, 4 << 20), ("time_s", *RAW_METRICS, *MOMENT_FIELDS))
            n = len(chunk["time_s"])
            shape = (n, len(rows))
            if (not 1 <= n <= 120 or not np.array_equal(chunk["time_s"], clock[index:index+n])
                    or any(chunk[k].shape != shape or chunk[k].dtype.kind != "f" for k in RAW_METRICS)
                    or chunk["moment_rowadr"].shape != shape or chunk["moment_rownnz"].shape != shape
                    or chunk["moment_columns"].shape != chunk["moment_values"].shape
                    or chunk["moment_values"].ndim != 2 or chunk["moment_values"].shape[0] != n):
                raise ValueError("muscle array dimensions or exact timestamps differ")
            field = {"force_magnitude_N": "force_N", "work_J": "power_W"}.get(metric, metric)
            series.append(chunk[field][:, ids])
            index += n
        if index != len(clock):
            raise ValueError("incomplete muscle time coverage")
        values = np.concatenate(series)
        if metric == "force_magnitude_N":
            values = np.abs(values)
        if metric == "work_J":
            values = np.vstack([np.zeros(len(ids)), np.cumsum(
                (values[:-1] + values[1:]) * (np.diff(clock)[:, None] / 2), axis=0)])
            ranking = json.loads(verified_bytes(root, manifest, "muscle_ranking.json", 1 << 20))
            work = {r["actuator"]: r["signed_mechanical_work_J"] for r in ranking["actuators"]}
            base.update(work_definition="Cumulative trapezoid of saved signed power from first source sample",
                        full_integrator_work_J=[work[rows[i]["exact_name"]] for i in ids],
                        full_integrator_work_definition="Source ranking integrated on solver steps over the full run")
        chosen = np.flatnonzero((clock >= lo) & (clock <= hi))
        page = chosen[offset:offset + stride * limit:stride]
        if offset > len(chosen):
            raise ValueError("sample offset exceeds the window")
        if any(digest(trajectory["states"][i].tobytes()) != frames[i]["state_sha256"] for i in page):
            raise ValueError("saved state SHA-256 differs from MotionScene")
        phases = {f["phase"]: f["state_index"] for f in frames if f["phase"] != "motion"}
        bottom = phases.get("bottom")
        if bottom is None or not 0 < bottom < len(frames) - 1:
            raise ValueError("missing bottom phase anchor")
        phase_labels = ["bottom" if i == bottom else "descent" if i < bottom else "ascent" for i in page]
        rule, aggregate = derived(metric, values) if group else (None, None)
        summary = {}
        if phase_summary:
            for name, mask in (("descent", chosen < bottom), ("bottom", chosen == bottom), ("ascent", chosen > bottom)):
                subset = chosen[mask]
                if len(subset):
                    summary[name] = {"inclusive_state_bounds": [int(subset[0]), int(subset[-1])],
                                     "sample_count": len(subset),
                                     "mean_per_path": values[subset].mean(axis=0).tolist()}
                    if aggregate is not None:
                        summary[name]["mean_derived"] = float(aggregate[subset].mean())
        bound = ["trajectory.npz", "trajectory_metadata.json", "actuators.json", *names]
        if metric == "work_J":
            bound.append("muscle_ranking.json")
        scientific = signal_evidence(context, metric, sources(manifest, *bound),
                                     {"requested_time_s": [float(lo), float(hi)], "sampling": "exact_saved_samples",
                                      "offset": offset, "stride": stride, "limit": limit},
                                     group=group, available=bool(len(page)))
        if rule:
            scientific["quantities"]["aggregate"] = {**MUSCLE[metric], "origin": DERIVED,
                                                     "native_identifier": None,
                                                     "definition": GROUP_DEFINITIONS[rule],
                                                     "availability": "AVAILABLE" if len(page) else "NO_DATA"}
        if phase_summary:
            scientific["quantities"]["phase_summary"] = {**MUSCLE[metric], "origin": DERIVED,
                "native_identifier": None,
                "definition": "Arithmetic mean of exact saved samples in the requested phase and time window, before pagination.",
                "availability": "AVAILABLE" if summary else "NO_DATA"}
        if metric == "work_J":
            scientific["quantities"]["full_integrator_work_J"] = MUSCLE["full_integrator_work_J"]
        return {**base, "mapping_status": "REVIEWED_ANATOMICAL" if group else "NATIVE_ONLY", "group": group,
                "data_status": "AVAILABLE" if len(page) else "NO_DATA", "scientific_quantity": scientific,
                "state_indices": page.tolist(), "time_s": clock[page].tolist(), "phases": phase_labels,
                "state_sha256": [frames[i]["state_sha256"] for i in page],
                "phase_anchors": phases, "window_sample_count": len(chosen),
                "next_offset": offset + stride * limit if offset + stride * limit < len(chosen) else None,
                "phase_summary": summary, "aggregation": rule,
                "aggregate": aggregate[page].tolist() if aggregate is not None else None,
                "series": [{"actuator_id": idx, "exact_name": rows[idx]["exact_name"],
                            "identity": signal_identity(rows[idx]),
                            "values": values[page, j].tolist()} for j, idx in enumerate(ids)]}

    def search(self, context, request):
        _, mapping, _, _, base = context
        if request.display_node is not None:
            node = str(request.display_node)
            asset = mapping["reviewed_display_assets"].get(node) or mapping["motion_display_assets"].get(node)
            if asset is None or (request.side and request.side != asset.get("side")):
                return {**base, "mapping_status": "UNMAPPED", "data_status": "NO_DATA",
                        "asset": None, "group": None, "rows": []}
            group = mapping["groups"].get(asset.get("group_id"))
            rows = [mapping["rows"][i] for i in group["actuator_ids"]] if group else []
            status = ("REVIEWED_ANATOMICAL" if asset.get("part_actuator_id") is not None else
                      "REVIEWED_GROUP_ONLY" if group else "GEOMETRY_ONLY")
            candidates = [r["id"] for r in mapping["rows"] if not r["group"] and asset.get("fma_id")
                          and any(c["fma_id"] == asset["fma_id"] for c in r["concept_membership"])]
            return {**base, "mapping_status": status, "data_status": "AVAILABLE" if rows else "NO_DATA",
                    "asset": asset, "group": group, "rows": rows,
                    "candidate_actuator_ids": candidates}
        q = request.query.casefold().strip()

        if request.inventory == "display":
            found = []
            for node, source in mapping["motion_display_assets"].items():
                asset = mapping["reviewed_display_assets"].get(node, source)
                status = "mapped" if asset.get("group_id") else "geometry_only"
                if request.status and request.status != status or request.side and request.side != asset.get("side"):
                    continue
                if request.region:
                    group = mapping["groups"].get(asset.get("group_id"), {})
                    if not any(mapping["rows"][i].get("region") == request.region for i in group.get("actuator_ids", [])):
                        continue
                identifiers = (node, asset["name"], asset["mesh_id"], asset.get("fj_label"), asset.get("fma_id"))
                if q and not any((q in value.casefold() if request.operation == "muscle.search" else q == value.casefold())
                                 for value in identifiers if value):
                    continue
                found.append({**asset, "selection_status": status})
            end = request.offset + request.limit
            return {**base, "mapping_status": "DISPLAY_INVENTORY", "rows": [], "assets": found[request.offset:end],
                    "count": len(found), "next_offset": end if end < len(found) else None}

        def matches(row):
            if request.side is not None and row["side"] != request.side:
                return False
            if request.region and row.get("region") != request.region:
                return False
            if request.status == "missing_asset":
                if row["display_assets"]:
                    return False
            elif request.status and request.status != {
                "REVIEWED_ANATOMICAL": "mapped", "CANDIDATE": "candidate", "CONFLICT": "conflict",
                "UNMAPPED": "unmapped", "NO_SOURCE_GEOMETRY": "missing_asset",
            }.get(row["status"]):
                return False
            if not q:
                return request.operation == "muscle.search"
            identifiers = [row["exact_name"], str(row["id"]), row["group"] or "",
                           *row["display_assets"], *(x["fma_id"] for x in row["concept_membership"]),
                           *(x["mesh_id"] for x in row["bodyparts3d"])]
            group = mapping["groups"].get(row["group"])
            if group and group["parent_fma_id"]:
                identifiers.append(group["parent_fma_id"])
            if request.operation == "muscle.search":
                identifiers += [x["label"] for x in row["concept_membership"]]
                parsed = row.get("canonical", {})
                identifiers += [parsed.get("source_label") or "", *parsed.get("vertebral_or_rib_tokens", []),
                                *parsed.get("head_or_segment_tokens", []),
                                row.get("registration_review", {}).get("family") or ""]
                return any(q in value.casefold() for value in identifiers)
            return q in {value.casefold() for value in identifiers}

        found = [row for row in mapping["rows"] if matches(row)]
        result = found[request.offset:request.offset + request.limit]
        if request.brief:
            result = [{**{k: row.get(k) for k in ("id", "exact_name", "side", "region", "status")},
                       "reviewed_labels": [c["label"] for c in row["concept_membership"]
                                           if c["status"] == "REVIEWED_ANATOMICAL"]} for row in result]
        exact_group = mapping["groups"].get(q)
        identity_status = ("UNMAPPED" if not found else "AMBIGUOUS" if any(r["status"] == "CONFLICT" for r in found)
                           or (len(found) > 1 and not exact_group) else found[0]["status"])
        if len(found) == 1:
            fma = [c for c in found[0]["concept_membership"] if c["fma_id"].casefold() == q]
            if fma and fma[0]["status"] != "REVIEWED_ANATOMICAL":
                identity_status = fma[0]["status"]
        return {**base, "mapping_status": identity_status, "data_status": "AVAILABLE" if result else "NO_DATA",
                "rows": result, "count": len(found),
                "next_offset": request.offset + request.limit if len(found) > request.offset + request.limit else None}

    def validate_view(self, context, index, selection, palette=True):
        scene, mapping, _, _, base = context
        if selection.mapping_revision_sha256 != self.sha or index >= len(scene["frames"]):
            raise ValueError("stale mapping revision or exact state unavailable")
        node = str(selection.display_node)
        asset = mapping["reviewed_display_assets"].get(node) or mapping["motion_display_assets"].get(node)
        if selection.display_node is not None and asset is None:
            raise ValueError("selection is not a muscle display node")
        row = mapping["rows"][selection.actuator_id] if selection.actuator_id is not None else None
        group = mapping["groups"].get(asset.get("group_id") if asset else row["group"])
        ids = group["actuator_ids"] if group else []
        if (row is not None and (asset is not None and row["id"] not in ids or selection.overlay)
                or (selection.overlay and not group)):
            raise ValueError("path and overlay are unavailable for the selected muscle")
        linked = [a["display_copy"] for a in mapping["reviewed_display_assets"].values()
                  if group and a["group_id"] == group["group_id"]]
        display_nodes = linked or ([asset["display_copy"]] if asset else [])
        if selection.isolate and not display_nodes:
            raise ValueError("isolation requires a display surface")
        if selection.opacity_scope != "selection" and asset is None:
            raise ValueError("surface or source opacity requires a display node")
        opacity_nodes = display_nodes
        if selection.opacity_scope == "surface":
            opacity_nodes = [asset["display_copy"]]
        if selection.opacity_scope == "source":
            opacity_nodes = [a["display_copy"] for a in mapping["motion_display_assets"].values()
                             if a["dataset"] == asset["dataset"]]
        result = {**base, "metric": selection.metric, "unit": UNITS[selection.metric],
                  "mapping_status": row["status"] if row else
                  "REVIEWED_ANATOMICAL" if asset.get("part_actuator_id") is not None else
                  "REVIEWED_GROUP_ONLY" if group else "GEOMETRY_ONLY",
                  "frame": scene["frames"][index], "selection": selection.model_dump(),
                  "asset": asset, "native": row, "group": group, "display_nodes": display_nodes,
                  "opacity_nodes": opacity_nodes}
        frame = result["frame"]
        result["data_status"] = "NO_DATA"
        result["scientific_quantity"] = signal_evidence(
            context, selection.metric, sources(context[3], "trajectory.npz"),
            {"state_index": index, "time_s": frame["frame_time"], "state_sha256": frame["state_sha256"],
             "sampling": "exact_saved_sample"}, asset=asset, group=group, available=False)
        if (ids or row) and palette:
            ts = scene["frames"][index]["frame_time"]
            signals = self.series(context, selection.metric,
                                  [selection.actuator_id] if selection.actuator_id is not None else [],
                                  group["group_id"] if selection.actuator_id is None else None, ts, ts)
            result["sample"] = {"aggregation": signals["aggregation"], "aggregate": signals["aggregate"],
                                "series": signals["series"]}
            if selection.metric == "work_J":
                result["sample"]["full_integrator_work_J"] = signals["full_integrator_work_J"]
            result["data_status"] = signals["data_status"]
            result["scientific_quantity"]["sources_sha256"] = signals["scientific_quantity"]["sources_sha256"]
            result["scientific_quantity"]["quantities"] = signals["scientific_quantity"]["quantities"]
            if selection.overlay:
                act = signals if selection.metric == "activation" else self.series(
                    context, "activation", [], group["group_id"], ts, ts)
                result["overlay"] = {"metric": "activation", "unit": "1",
                    "formula": "arithmetic_mean_of_paths", "value": act["aggregate"][0],
                    "linear_rgb": activation_color(act["aggregate"][0]),
                    "linear_rgb_at_0": activation_color(0), "linear_rgb_at_1": activation_color(1),
                    "display_nodes": [a["display_copy"] for a in mapping["reviewed_display_assets"].values()
                                      if a["group_id"] == group["group_id"] and a["part_actuator_id"] is not None]}
                result["scientific_quantity"]["quantities"]["overlay"] = MUSCLE["overlay"]
        if asset:
            result["scientific_quantity"]["quantities"]["display_surface"] = MUSCLE["display_surface"]
        return result

    def registration(self, context, request):
        scene, mapping, _, _, base = context
        if (request.motion_sha256 != self.whole.sha or request.mapping_revision_sha256 != self.sha
                or request.state_index >= len(scene["frames"])):
            raise ValueError("stale motion or crosswalk revision, or exact state unavailable")
        node = str(request.display_node)
        asset = mapping["reviewed_display_assets"].get(node) or mapping["motion_display_assets"].get(node)
        group = mapping["groups"].get(request.group_id or (asset or {}).get("group_id"))
        native = mapping["rows"][request.actuator_id] if request.actuator_id is not None else None
        side = (asset or native or group or {}).get("side")
        if request.side is not None and request.side != side:
            asset = group = native = None
        rows = [native] if native else [mapping["rows"][i] for i in group["actuator_ids"]] if group else []
        end = request.offset + request.limit
        status = native["status"] if native else (
            "REVIEWED_ANATOMICAL" if asset and asset.get("part_actuator_id") is not None else
            "REVIEWED_GROUP_ONLY" if group else "GEOMETRY_ONLY" if asset else "UNMAPPED")
        frame = scene["frames"][request.state_index]
        page = rows[request.offset:end]
        evidence = {}
        if request.evidence_frame:
            if request.evidence_revision_sha256 and request.evidence_revision_sha256 != self.evidence_sha:
                raise ValueError("stale registration evidence revision")
            if not self.evidence_path or not self.evidence_sha:
                evidence = {"status": "NOT_INSTALLED"}
            else:
                report = load_evidence(self.evidence_path, self.evidence_sha)
                evidence = at_frame(report, self.evidence_sha, base, frame,
                                    [row["exact_name"] for row in page], node if asset else None)
        return {**base, "mapping_status": status, "frame": frame,
                **({"evidence": evidence} if evidence else {}),
                "route_frame": "MuJoCo body-local metres for model sites",
                "attachment_footprint": "NOT_VERIFIED", "deformation_validation": "NOT_VERIFIED",
                "asset": asset, "group": group, "count": len(rows),
                "next_offset": end if end < len(rows) else None,
                "rows": [{k: row[k] for k in ("id", "exact_name", "side", "region", "tendon_id", "tendon_name",
                                             "links", "concept_membership", "display_assets", "status_axes",
                                             "reason_codes", "canonical", "registration_review") if k in row}
                         for row in page]}

    def call(self, request):
        context = self.context(request.run_id)
        if isinstance(request, MuscleRegistration):
            return self.registration(context, request)
        if isinstance(request, MuscleSearch):
            return self.search(context, request)
        if isinstance(request, MuscleSeries):
            if request.unit is not None and request.unit != UNITS[request.metric]:
                return error("invalid_input", "requested unit is incompatible with the saved quantity")
            return self.series(context, request.metric, request.actuator_ids, request.group_id, request.start_s,
                               request.end_s, request.offset, request.limit, request.stride, request.phase_summary)
        if isinstance(request, MuscleSelection):
            if not self.selection_path or not self.selection_path.exists():
                return {**context[-1], "mapping_status": "NO_SELECTION", "selection": None}
            raw = read_bounded(self.selection_path, 8 << 10)
            stored = MuscleSelect.model_validate_json(raw)
            if stored.motion_sha256 != self.whole.sha or stored.run_id != request.run_id:
                raise ValueError("stored selection belongs to a different MotionScene")
            return {**self.validate_view(context, stored.state_index, stored.selection), "selection_sha256": digest(raw)}
        if request.motion_sha256 != self.whole.sha:
            raise ValueError("stale MotionScene revision")
        result = self.validate_view(context, request.state_index, request.selection)
        if request.publish:
            if self.selection_path is None:
                raise ValueError("shared selection storage not installed")
            raw = canonical(request.model_dump(mode="json", exclude={"if_match"}))
            with file_lock(self.selection_path.with_suffix(".lock")):
                if request.if_match and (not self.selection_path.exists() or
                        digest(read_bounded(self.selection_path, 8 << 10)) != request.if_match):
                    raise ValueError("shared selection changed")
                with NamedTemporaryFile(dir=self.selection_path.parent, prefix=".muscle-view-", delete=False) as out:
                    tmp = Path(out.name)
                    try:
                        out.write(raw)
                        out.flush()
                        os.replace(tmp, self.selection_path)
                    finally:
                        tmp.unlink(missing_ok=True)
            result["selection_sha256"] = digest(raw)
        return result
