"""Independently re-evaluate saved poses and audit source signals used in the report."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

import mujoco as mj
import numpy as np

from human_models_mcp.scene_export import load_saved_run
from glb import B4


def sha(value):
    return hashlib.sha256(value).hexdigest()


def audit(run_dir, clip):
    run, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(run_dir)
    motion = json.loads((clip / "motion.json").read_bytes())
    data_clip = json.loads((clip / "samples.json").read_bytes())
    geometries = json.loads((clip / "geometry.json").read_bytes())["pose_geometry_id_order"]
    recorded = np.stack([data_clip["geom_pose_world_m"][str(g)] for g in geometries], axis=1)
    if sha((run_dir / "manifest.json").read_bytes()) != motion["source_manifest_sha256"]:
        raise ValueError("run manifest does not match the replay")
    actual = np.repeat(np.eye(4)[None, None], len(states) * len(geometries), axis=0)
    actual = actual.reshape(len(states), len(geometries), 4, 4)
    cover = json.loads((clip / "coverage.json").read_bytes())
    frame_metrics, sites = [], {}
    body_delta_max = 0.
    for i, state in enumerate(states):
        mj.mj_setState(model, data, state, spec)
        mj.mj_kinematics(model, data)
        assert np.array_equal(data.qpos, qpos[i]) and data.time == times[i]
        frame = motion["frames"][i]
        assert i == frame["state_index"] and data.time == frame["frame_time"]
        assert sha(state.tobytes()) == frame["state_sha256"]
        actual[i, :, :3, 3] = data.geom_xpos[geometries]
        actual[i, :, :3, :3] = data.geom_xmat[geometries].reshape(-1, 3, 3)
        assert sha(actual[i].astype("<f8").tobytes()) == frame["native_transform_sha256"]
        for row in cover["native_bones"]:
            body = model.body(row["body"]).id
            body_world = np.eye(4)
            body_world[:3, :3] = data.xmat[body].reshape(3, 3)
            body_world[:3, 3] = data.xpos[body]
            d = body_world @ np.asarray(row["geom_relative_to_body_m"])
            g = geometries.index(row["geom_id"])
            body_delta_max = max(body_delta_max, float(np.max(np.abs(d - recorded[i, g]))))
        if i in (0, len(states) // 4, len(states) // 2, len(states) * 3 // 4, len(states) - 1):
            sites[str(i)] = {name: data.site_xpos[s].tolist() for s in range(model.nsite)
                             if (name := model.site(s).name).startswith(("PECM1_r-", "PECM1_l-"))}
        frame_metrics.append({"source_index": i, "time_s": float(data.time), "state_sha256": frame["state_sha256"],
                              "native_transform_sha256": frame["native_transform_sha256"], "match": True})
    if not np.array_equal(actual, recorded) or body_delta_max > 1e-12:
        raise ValueError("native site/geometry transport mismatch")
    truth = B4 @ actual @ B4.T
    g_r = geometries.index(model.geom("humerus").id)
    g_l = geometries.index(model.geom("humerus_mirror").id)
    wrong = {"native_Z_up_passed_as_glTF": actual,
             "handedness_reflected": np.diag([1, 1, -1, 1]) @ truth @ np.diag([1, 1, -1, 1]),
             "millimetres_as_metres": np.copy(truth),
             "swapped_humeri": np.copy(truth)}
    wrong["millimetres_as_metres"][..., :3, 3] *= 1000
    wrong["swapped_humeri"][:, [g_r, g_l]] = truth[:, [g_l, g_r]]
    negatives = {name: float(np.max(np.abs(candidate - truth))) for name, candidate in wrong.items()}
    assert min(negatives.values()) > .01
    return {"run_id": run["run_id"], "native_matrix_component_error_max": float(np.max(np.abs(actual-recorded))),
            "body_bind_reconstruction_error_max": body_delta_max,
            "frames": frame_metrics, "key_model_sites": sites, "negative_max_matrix_component_errors": negatives,
            "summary": json.loads((run_dir / "summary.json").read_bytes()),
            "native_signals": signals(run, run_dir)}


def signals(run, run_dir):
    source = json.loads((run_dir / "actuators.json").read_bytes())["actuators"]
    groups = defaultdict(list)
    for a in source:
        name = a["name"]
        side = name[-1] if name.endswith(("_r", "_l")) else None
        if not side:
            continue
        prefix = name[:-2]
        if re.fullmatch(r"PECM[123]", prefix):
            group = "pectoralis_major"
        elif re.fullmatch(r"TRI(?:long|lat|med)", prefix, re.I):
            group = "triceps"
        elif re.fullmatch(r"(?:serr_ant|SERAT|rect_abd|extobl|intobl)\d*", prefix, re.I):
            group = "trunk_stabilizers_selected"
        else:
            continue
        groups[(group, side)].append((a["id"], name))
    fields = ("time_s", "excitation", "activation", "force_N", "length_m", "velocity_m_per_s", "power_W")
    rows = defaultdict(list)
    for path in sorted(run_dir.glob("muscles_*.npz")):
        if sha(path.read_bytes()) != run["artifacts"][path.name]["sha256"]:
            raise ValueError("native actuator data differs from manifest")
        with np.load(path, allow_pickle=False) as data:
            for field in fields:
                rows[field].append(data[field])
    values = {k: np.concatenate(v) for k, v in rows.items()}
    time = values["time_s"]
    peak = len(time) // 2
    result = {}
    for (group, side), tracks in sorted(groups.items()):
        ids, names = zip(*tracks, strict=True)
        phases = {}
        for phase, sl in (("descent", slice(5, peak + 1)), ("ascent", slice(peak, len(time) - 5))):
            force = values["force_N"][sl][:, ids]
            power = values["power_W"][sl][:, ids]
            phases[phase] = {"time_limits_s": [float(time[sl][0]), float(time[sl][-1])],
                "mean_excitation": float(values["excitation"][sl][:, ids].mean()),
                "mean_activation": float(values["activation"][sl][:, ids].mean()),
                "mean_sum_abs_force_N": float(np.abs(force).sum(1).mean()),
                "mean_length_m": float(values["length_m"][sl][:, ids].mean()),
                "mean_velocity_m_per_s": float(values["velocity_m_per_s"][sl][:, ids].mean()),
                "signed_work_J": float(np.trapezoid(power.sum(1), x=time[sl]))}
        result[group + "_" + side] = {"actuators": list(names), "phases": phases}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("clip", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.run, args.clip)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"native transforms: {len(result['frames'])} exact checks; body reconstruction "
          f"{result['body_bind_reconstruction_error_max']:.3g}; {len(result['native_signals'])} signal groups")


if __name__ == "__main__":
    main()
