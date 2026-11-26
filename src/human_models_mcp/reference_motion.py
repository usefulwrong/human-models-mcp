"""Local Fit3D BYO importer and one-cycle comparison of equivalent geometric observables."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .registry import home
from .rendering import snapshot, write_json
from .results import get_run
from .scene_export import load_saved_run, restore_state

SOURCE = {
    "dataset": "Fit3D", "url": "https://fit3d.imar.ro/fit3d", "format": "joints3d_25 JSON",
    "license": "Fit3D personal non-commercial terms", "license_url": "https://fit3d.imar.ro/legal",
    "redistribution": "local licensed workspace only",
}
IDS = ("pelvis", "hip_r", "knee_r", "ankle_r", "hip_l", "knee_l", "ankle_l",
       "shoulder_l", "elbow_l", "wrist_l", "shoulder_r", "elbow_r", "wrist_r")
FIT3D_INDICES = (0, 1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16)
MODEL_JOINTS = (None, "hip_flexion_r", "knee_angle_r", "ankle_angle_r", "hip_flexion_l", "knee_angle_l", "ankle_angle_l",
                "shoulder_elv_l", "elbow_flexion_l", "flexion_l", "shoulder_elv_r", "elbow_flexion_r", "flexion_r")
LIMBS = ((1, 2), (2, 3), (4, 5), (5, 6), (7, 8), (8, 9), (10, 11), (11, 12))
EDGES = (*LIMBS, (0, 1), (0, 4), (0, 7), (0, 10), (7, 10))
MISSING = {"status": "NOT_RUN", "reason": "LICENSED_DATA_NOT_PROVIDED", "source": SOURCE}


class ClipMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=100)
    motion: str = Field(pattern=r"^push[_ -]?ups?$")
    phase_frames: list[int] = Field(min_length=3, max_length=3)
    world_to_zup: list[list[Literal[-1, 0, 1]]]
    floor_z_m: float
    coordinate_system: str = Field(min_length=1, max_length=200)
    unit: str
    camera: str = Field(min_length=1, max_length=100)


def import_fit3d(path, metadata, accepted_license):
    """Use annotated start/bottom/return indices, metres, and an explicit proper axis conversion."""
    if accepted_license is not True:
        raise ValueError("Fit3D terms and licensed local access must be acknowledged")
    path = Path(path).resolve()
    if path.is_relative_to(home().resolve()):
        raise ValueError("Keep Fit3D inputs outside the project tree")
    meta = ClipMetadata.model_validate(metadata)
    axes = np.asarray(meta.world_to_zup)
    if (meta.unit != "m" or meta.camera != "world" or axes.shape != (3, 3)
            or not np.array_equal(axes @ axes.T, np.eye(3)) or np.linalg.det(axes) != 1):
        raise ValueError("Fit3D requires metres, world coordinates and a proper signed axis permutation")
    if not 0 < path.stat().st_size <= 40 * 1024 * 1024:
        raise ValueError("Fit3D source exceeds 40 MiB or is empty")
    raw = path.read_bytes()
    source = json.loads(raw)
    if not isinstance(source, dict) or "joints3d_25" not in source:
        raise ValueError("Fit3D joints3d_25 JSON key required")
    xyz = np.asarray(source["joints3d_25"])
    if xyz.ndim != 3 or xyz.shape[1:] != (25, 3) or xyz.dtype.kind not in "iuf":
        raise ValueError("expected numeric Fit3D T×25×3 world joints")
    start, bottom, stop = meta.phase_frames
    if not 0 <= start < bottom < stop < len(xyz) or not 15 <= stop - start <= 600:
        raise ValueError("require annotated start, bottom and return phase indices within one 0.3–12 s clip")
    xyz = xyz[start:stop + 1, FIT3D_INDICES, :] @ axes.T
    xyz[..., 2] -= meta.floor_z_m
    if not np.isfinite(xyz).all():
        raise ValueError("nonfinite or missing 3D joints in clip")
    lengths = np.linalg.norm(xyz[:, [a for a, _ in LIMBS]] - xyz[:, [b for _, b in LIMBS]], axis=2)
    median = np.median(lengths, axis=0)
    if np.any(median < .12) or np.any(median > .65) or np.max(np.abs(lengths / median - 1)) > .25:
        raise ValueError("inconsistent limb geometry, joint order or source units")
    shoulders = xyz[:, [7, 10], 2].mean(1)
    if (xyz[..., 2].min() < -.05 or xyz[..., 2].max() > 1.5
            or np.median(xyz[:, [9, 12], 2]) > .22
            or min(shoulders[0], shoulders[-1]) - shoulders[bottom - start] < .04
            or np.linalg.norm((xyz[0, [7, 10]].mean(0) - xyz[0, 0])[:2]) < .2):
        raise ValueError("floor, up axis or annotated push-up phases are inconsistent")
    forward = (xyz[0, [7, 10]].mean(0) - xyz[0, 0])[:2]
    left = (xyz[0, 7] - xyz[0, 10])[:2]
    if forward[0] * left[1] - forward[1] * left[0] <= .02:
        raise ValueError("left-right shoulder orientation inconsistent with a right-handed floor plane")
    return {
        "schema_version": "1.0", "source": {**SOURCE, "version": meta.version},
        "provenance": {"source_sha256": hashlib.sha256(raw).hexdigest(), **meta.model_dump()},
        "joint_ids": list(IDS), "dataset_joint_indices": list(FIT3D_INDICES), "fps": 50,
        "camera": "world", "coordinates": "right-handed Z-up; caller supplies axis permutation and floor",
        "unit": "m", "time_s": (np.arange(len(xyz)) / 50).tolist(), "joints_m": xyz.tolist(),
    }


def simulate_landmarks(run_id):
    run = get_run(run_id)
    if run.get("status") != "computed" or run["scenario_id"] not in {"pushup", "pushup_palms", "pushup_flat_palm"}:
        raise ValueError("comparison requires a supported computed push-up")
    with TemporaryDirectory() as temp:
        source = Path(temp) / "snapshot"
        files = snapshot(run, source)
        _, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(source)
        phases = json.loads((source / "summary.json").read_text())["key_indices"]
        xyz = []
        ids = [model.joint(name).id for name in MODEL_JOINTS[1:]]
        pelvis = model.body("pelvis").id
        for index, state in enumerate(states):
            restore_state(model, data, state, spec, qpos[index], times[index])
            xyz.append(np.vstack([data.xpos[pelvis], data.xanchor[ids]]))
    return np.asarray(xyz), times, phases, files["trajectory.npz"]


def compare_motion(reference, simulated, times, phase_indices):
    """Align one reference clip by fixed yaw, translation and scale, then compare on an affine phase clock."""
    ref = np.asarray(reference["joints_m"])
    rt = np.asarray(reference["time_s"])
    times = np.asarray(times)
    if rt.ndim != 1 or times.ndim != 1 or min(rt.size, times.size) < 3:
        raise ValueError("incompatible reference/model landmarks or clocks")
    st = times - times[0]
    if (ref.shape != (len(rt), len(IDS), 3) or simulated.shape != (len(st), len(IDS), 3)
            or not all(np.isfinite(values).all() for values in (ref, simulated, rt, st))
            or not np.all(np.diff(rt) > 0) or not np.all(np.diff(st) > 0) or rt[0] != 0):
        raise ValueError("incompatible reference/model landmarks or clocks")
    ratio = []
    for a, b in LIMBS:
        r_len = np.median(np.linalg.norm(ref[:, a] - ref[:, b], axis=1))
        s_len = np.median(np.linalg.norm(simulated[:, a] - simulated[:, b], axis=1))
        if min(r_len, s_len) <= 1e-6:
            raise ValueError("degenerate joint segment")
        ratio.append(float(s_len / r_len))
    scale = float(np.median(ratio))
    if not .65 <= scale <= 1.5 or max(abs(np.asarray(ratio) / scale - 1)) > .35:
        raise ValueError("anthropometry incompatible with bounded global scale")
    headings = []
    for clip in (ref, simulated):
        v = clip[0, [7, 10]].mean(0) - clip[0, 0]
        if np.linalg.norm(v[:2]) < .20:
            raise ValueError("indeterminate horizontal heading")
        headings.append(np.arctan2(v[1], v[0]))
    yaw = float(headings[1] - headings[0])
    c, s = np.cos(yaw), np.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    aligned = (ref @ rotation.T) * scale
    translation = simulated[0, 0] - aligned[0, 0]
    translation[2] = 0  # Both floor planes are at Z=0 in metres.
    aligned += translation
    at = st * rt[-1] / st[-1]
    sampled = np.column_stack([np.interp(at, rt, column) for column in aligned.reshape(len(rt), -1).T])
    sampled = sampled.reshape(simulated.shape)
    distances = np.linalg.norm(sampled - simulated, axis=2)
    sim_bottom = phase_indices[1]
    start, ref_bottom, _ = reference["provenance"]["phase_frames"]
    ref_bottom -= start
    if not 0 < sim_bottom < len(st) - 1 or not 0 < ref_bottom < len(rt) - 1:
        raise ValueError("invalid comparison phase indices")
    elbow_error = {}
    for side, a in (("left", 7), ("right", 10)):
        angles = []
        for clip in (simulated, sampled):
            upper, lower = clip[:, a] - clip[:, a + 1], clip[:, a + 2] - clip[:, a + 1]
            denom = np.linalg.norm(upper, axis=1) * np.linalg.norm(lower, axis=1)
            if np.any(denom <= 1e-8):
                raise ValueError("degenerate elbow angle")
            angles.append(np.arccos(np.clip(np.sum(upper * lower, axis=1) / denom, -1, 1)))
        elbow_error[side] = float(np.sqrt(np.mean(np.square(angles[0] - angles[1]))))
    heights = [xyz[:, [7, 10], 2].mean(1) for xyz in (simulated, sampled)]
    return {
        "status": "COMPARED", "source": reference["source"], "dataset_frame_count": len(rt),
        "usable_simulated_frames": len(st), "joint_ids": list(IDS),
        "alignment": {"procedure": "fixed start heading and horizontal pelvis alignment; common floor; limb-median scale",
                      "source_segment_to_model_ratios": ratio, "scale": scale, "yaw_rad": yaw,
                      "translation_m": translation.tolist(), "start_mpjpe_m": float(distances[0].mean())},
        "time_alignment": {"procedure": "affine duration alignment, no DTW", "reference_duration_s": float(rt[-1]),
                           "simulation_duration_s": float(st[-1]), "reference_seconds_per_sim_second": float(rt[-1] / st[-1]),
                           "reference_bottom_time_s": float(rt[ref_bottom]), "simulation_bottom_time_s": float(st[sim_bottom]),
                           "bottom_phase_difference": float(st[sim_bottom] / st[-1] - rt[ref_bottom] / rt[-1])},
        "metrics": {"mpjpe_m": float(distances.mean()), "mean_error_per_joint_m": dict(zip(IDS, distances.mean(0).tolist(), strict=True)),
                    "elbow_internal_angle_rmse_rad": elbow_error,
                    "shoulder_midpoint_height_rmse_m": float(np.sqrt(np.mean(np.square(heights[0] - heights[1]))))},
        "limitations": ["Joint-centre definitions and anthropometry differ. Geometric elbow angles are measured between segments.",
                        "Timing alignment rescales duration and cannot establish natural execution speed.",
                        "No force, EMG, pressure, tissue or safety data are provided.",
                        "Dataset provenance, annotation and floor calibration are operator supplied."],
    }, sampled


def write_comparison(run_id, path, metadata, destination, accepted_license=False):
    """Local API. Reference data and derived overlays stay outside the project and render queue."""
    if path is None:
        return MISSING.copy()
    destination = Path(destination).resolve()
    if destination.is_relative_to(home().resolve()):
        raise ValueError("Write Fit3D derivatives to a private directory outside the project tree")
    reference = import_fit3d(path, metadata, accepted_license)
    simulated, times, phases, state_hash = simulate_landmarks(run_id)
    report, sampled = compare_motion(reference, simulated, times, phases)
    report.update(run_id=run_id, trajectory_sha256=state_hash, reference_provenance=reference["provenance"],
                  evidence_class="compared_with_external_data", validation_status="unvalidated")
    destination.mkdir(mode=0o700, parents=True)
    write_json(destination / "reference_motion.json", reference)
    write_json(destination / "comparison.json", report)
    plot_overlay(destination / "reference_overlay.png", simulated, sampled, times, phases)
    return report


def plot_overlay(path, simulated, sampled, times, phases):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, plots = plt.subplots(3, 2, figsize=(9, 9), layout="constrained")
    for row, index, title in zip(plots, phases, ("Start", "Bottom", "Return"), strict=True):
        for panel, horizontal, view in zip(row, (0, 1), ("Sagittal", "Frontal"), strict=True):
            for xyz, color, label in ((simulated, "#15548f", "Simulation"), (sampled, "#c55332", "Reference")):
                for n, edge in enumerate(EDGES):
                    points = xyz[index, list(edge)]
                    panel.plot(points[:, horizontal], points[:, 2], color=color, label=label if n == 0 else None)
            panel.set(title=f"{title} · {view} · {times[index]:.2f} s", xlabel="m", ylabel="Z (m)", aspect="equal")
            panel.legend(loc="best")
    figure.savefig(path, dpi=150)
    plt.close(figure)
