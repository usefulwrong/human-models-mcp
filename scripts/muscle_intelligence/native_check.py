"""Audit exact saved-state transforms, pilot endpoint positions and sparse derivatives."""

import argparse
import json
from pathlib import Path

import mujoco as mj
import numpy as np

from audit_native import audit
from human_models_mcp.scene_export import load_saved_run


def main(args):
    results = audit(args.run, args.clip)
    run, model, data, _, _, states, times, _, spec, _ = load_saved_run(args.run)
    crosswalk = json.loads(args.crosswalk.read_bytes())
    active = [r for r in crosswalk["rows"] if r["group"] is not None]
    endpoints = {r["exact_name"]: [s["object_id"] for s in r["links"] if s["kind"] == "site"]
                 for r in active}
    positions = {name: [] for name in endpoints}
    for state in states:
        mj.mj_setState(model, data, state, spec)
        mj.mj_kinematics(model, data)
        for name, (first, *_, last) in endpoints.items():
            positions[name].append(data.site_xpos[[first, last]].tolist())

    source = {}
    keys = ("moment_values", "moment_columns", "moment_rowadr", "moment_rownnz")
    chunks = []
    for name in run["outputs"]["muscles"]["chunks"]:
        with np.load(args.run / name, allow_pickle=False) as archive:
            chunks.append([archive[v] for v in keys])
    moments, columns, offsets, counts = (np.concatenate(v) for v in zip(*chunks, strict=True))
    for check in crosswalk["moment_arm_check"]["rows"]:
        name, i = check["name"], check["state_index"]
        aid = model.actuator(name).id
        dof = int(model.joint(check["hinge"]).dofadr[0])
        pos = range(offsets[i, aid], offsets[i, aid] + counts[i, aid])
        value = sum(float(moments[i, p]) for p in pos if columns[i, p] == dof)
        if abs(value - check["native_dL_dq_m_per_rad"]) > 1e-10 or check["absolute_error_m_per_rad"] > 1e-6:
            raise ValueError(f"recorded vs forward or finite difference consistency failed: {name} #{i}")
        source[f"{name}:{i}"] = value
    receipt = {"run_id": results["run_id"], "basis": "MuJoCo world meters", "state_indices": list(range(len(times))),
               "endpoints_m": positions, "moment_dL_dq_at_saved_states": source}
    args.output.mkdir(exist_ok=True)
    for name, content in (("native.json", results), ("endpoints.json", receipt)):
        (args.output / name).write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Exact state/native matrices:", len(results["frames"]), results["native_matrix_component_error_max"])
    print("Saved sparse J vs finite difference:", len(source), crosswalk["moment_arm_check"]["max_error"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("run", "clip", "crosswalk", "output"):
        parser.add_argument(f"--{field}", required=True, type=Path)
    main(parser.parse_args())
