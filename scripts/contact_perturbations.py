"""Negative controls from the same saved state under held, recorded joint input."""

import argparse
from pathlib import Path

import mujoco as mj
import numpy as np

from human_models_mcp.adapters.contact import dump, shift_root
from human_models_mcp.adapters.contact_geometry import FloorHistory, mesh_vertices
from human_models_mcp.scene_export import load_saved_run, restore_state


def trial(source, proxy_off, floor_raise_m, root_down_m):
    run, model, data, _, _, states, times, qpos, spec, _ = load_saved_run(source)
    index = int(np.argmin(abs(times - .2)))
    restore_state(model, data, states[index], spec, qpos[index], times[index])
    floor = model.geom("floor").id
    if proxy_off:
        for g in range(model.ngeom):
            if model.geom(g).name.startswith("palm_r_surface_"):
                model.geom_contype[g] = 0
    if floor_raise_m:
        model.geom_pos[floor, 2] += floor_raise_m
        mj.mj_setConst(model, data)
        restore_state(model, data, states[index], spec, qpos[index], times[index])
    shift_root(mj, model, data, np.array([0, 0, -root_down_m]))
    right = model.geom("hand_detail_r_thumbdist").id
    samples = []
    history = FloorHistory(mj, model, floor)
    points = mesh_vertices(model, right)
    for i in range(round(.08 / model.opt.timestep) + 1):
        if i:
            mj.mj_step(model, data)
        mj.mj_forward(model, data)
        history.record(data, i)
        gap = float((points @ data.geom_xmat[right, 6:9]).min() + data.geom_xpos[right, 2] - data.geom_xpos[floor, 2])
        right_load = sum(e[4][0] for e in history.rows[-1][2] if model.geom(e[0]).name.startswith("palm_r_surface_"))
        samples.append({"time_s": float(data.time), "right_thumb_signed_m": gap, "right_palm_force_N": right_load,
                        "right_wrist_world_m": data.xpos[model.body("hand_r").id].tolist(),
                        "warnings": data.warning.number.tolist()})
    return {"run_id": run["run_id"], "source_index": index,
            "floor_raise_m": floor_raise_m, "root_down_m": root_down_m,
            "right_hand_contact_mask_disabled": proxy_off,
            "method": "80 ms forward integration at held saved actuator inputs and external generalized joint force",
            "samples": samples, **history.report()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    controls = {"nominal": trial(args.run, False, 0, 0), "mask": trial(args.run, True, 0, 0),
                "floor": trial(args.run, False, .003, 0), "root": trial(args.run, False, 0, .002)}
    assert all(row["right_palm_force_N"] == 0 for row in controls["mask"]["samples"])
    for name, value in (("floor", .003), ("root", .002)):
        difference = controls["nominal"]["samples"][0]["right_thumb_signed_m"] - controls[name]["samples"][0]["right_thumb_signed_m"]
        assert abs(difference - value) < 1e-12
    dump(args.output, controls)
