"""Probe palms at shoulder/chest level with native limits; not a human feasibility proof."""

import argparse
import json
from pathlib import Path

import numpy as np

from human_models_mcp.adapters.hands import measure_palm_technique, palm_placement_passes
from human_models_mcp.adapters.pushup import pushup_model
from human_models_mcp.adapters.supports import fixed_reference_poses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/pushup-shoulder/probe"))
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    attempts = []
    for level in ("shoulders", "chest"):
        mj, model, data = pushup_model(timestep_s=.0005, hand_support="palms", support_boundary="fixed_points")
        ranges = model.jnt_range.copy()
        stage = "initial_placement"
        try:
            top, _ = fixed_reference_poses(mj, model, data, initial_only=True, forward_palms=True,
                                           hand_half_width=.22, palm_level=level)
            model.key_qpos[0] = top[0]
            data.qpos[:] = top[0]
            mj.mj_forward(model, data)
            assert palm_placement_passes([measure_palm_technique(model, data)])
            stage = "fixed_floor_cycle"
            cycle, info = fixed_reference_poses(mj, model, data, peak_elbow=1.8, forward_palms=True)
        except ValueError as error:
            result = {"status": "REFERENCE_NOT_REPRODUCED", "stage": stage, "error": str(error)}
        else:
            np.savez_compressed(output / (level + "-cycle.npz"), qpos=cycle)
            result = {"status": "IK_CLOSED_REQUIRES_TECHNIQUE_AND_DYNAMICS_REVIEW", "ik": info}
        assert np.array_equal(model.jnt_range, ranges)
        mj.mj_forward(model, data)
        result.update(target=level, geometry=measure_palm_technique(model, data), source_joint_ranges_unchanged=True)
        np.savez_compressed(output / (level + "-last-attempt.npz"), qpos=data.qpos)
        attempts.append(result)
    result = {"attempts": attempts, "requested_peak_elbow_rad": 1.8,
        "placement_target": "actual palm supports at shoulder/chest level; head is not a target",
        "references": "scenarios/pushup_palms/references.md",
        "interpretation": "Local bounded IK diagnostic, not a proof that a human or another model cannot perform this movement. No dynamics or successful full push-up claimed."}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"attempts": [{"target": r["target"], "status": r["status"]} for r in attempts], "output": str(output)}))


if __name__ == "__main__":
    main()
