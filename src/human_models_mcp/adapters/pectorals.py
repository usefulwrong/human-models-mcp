"""Recorded bilateral native pectoral paths; no EMG or inferred tissue forces."""

import csv

import numpy as np

from .contact import dump


def write_pectorals(output, model, rows, muscle_samples, ranking, cycle_s):
    names = [f"PECM{bundle}_{side}" for side in "rl" for bundle in (1, 2, 3)]
    ids = [model.actuator(name).id for name in names]
    stats = {a["actuator"]: a for a in ranking}
    records = []
    for row, muscles in zip(rows, muscle_samples, strict=True):
        t = row["time_s"]
        phase = ("settling" if t < .2 - 1e-10 else "lowering" if t < .2 + cycle_s / 2 - 1e-10
                 else "raising" if t < .2 + cycle_s - 1e-10 else "holding")
        for name, aid in zip(names, ids, strict=True):
            records.append({"sample": row["sample"], "time_s": t, "reference_phase": phase,
                "actuator": name, "side": name[-1], "source_bundle": name.split("_")[0],
                "excitation": float(muscles["excitation"][aid]),
                "activation": float(muscles["activation"][model.actuator_actadr[aid]]),
                **{key: float(muscles[key][aid]) for key in ("force_N", "length_m", "velocity_m_per_s", "power_W")}})
        for side in "rl":
            selected = [record for record in records[-6:] if record["side"] == side]
            row[f"pectoralis_{side}_activation"] = float(np.mean([v["activation"] for v in selected]))
            row[f"pectoralis_{side}_absolute_path_force_N"] = sum(abs(v["force_N"]) for v in selected)
            row[f"pectoralis_{side}_power_W"] = sum(v["power_W"] for v in selected)
    with (output / "pectorals.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    dump(output / "pectorals.json", {
        "actuators": [{**stats[name], "source_bundle": name.split("_")[0], "side": name[-1]} for name in names],
        "series": "pectorals.csv", "sample_count": len(rows), "path_count": len(names),
        "units": {"excitation": "1", "activation": "1", "force_N": "N", "length_m": "m",
                  "velocity_m_per_s": "m/s", "power_W": "W", "absolute_force_impulse_Ns": "N*s", "signed_mechanical_work_J": "J"},
        "force": "Signed native tendon-transmission force; tensile values are generally negative. Per-side absolute sums are path magnitudes, not net chest/joint force.",
        "work": "Signed force*transmission velocity integrated at every engine step; not estimated from the coarser CSV samples.",
        "phase": "Controller protocol phases (0.2 s settling, half cycle lowering, half raising, 0.2 s hold), not observed muscle-fibre contraction labels.",
        "mapping": "Literal native PECM1/2/3 identifiers; no unverified mapping to clinical subheads or pectoralis minor.",
        "interpretation": "Computed model activation is not normalized surface EMG; force and work are not injury or tissue-stress predictions."})
