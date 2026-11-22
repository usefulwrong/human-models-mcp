"""Summarize named native torso actuators in a saved push-up run."""

import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np


GROUPS = {
    "rectus_abdominis": r"rect_abd_[rl]",
    "external_oblique": r"EO_R(?:[5-9]|1[0-2])_[rl]",
    "internal_oblique": r"IO[1-6]_[rl]",
    "transversus_abdominis": r"TR[1-5]_[rl]",
    "iliocostalis": r"IL_.*_[rl]",
    "longissimus": r"LTp.*_[rl]",
    "multifidus": r"(?:MF_|multifidus_).*",
    "quadratus_lumborum": r"QL_.*_[rl]",
    "latissimus_dorsi": r"LD_.*_[rl]",
    "trapezius": r"trap_.*",
    "pectoralis_major": r"PECM[1-3]_[rl]",
    "serratus_anterior": r"SerrAnt[1-9]_[12]_[RL]",
}


def summarize(run):
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["scenario_id"] != "pushup_palms":
        raise ValueError("expected a saved pushup_palms run")
    used = {}

    def verified(name):
        path = run / name
        entry = manifest["artifacts"][name]
        if path.is_symlink() or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"saved artifact length differs: {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"saved artifact hash differs: {name}")
        used[name] = digest
        return path

    actuators = json.loads(verified("actuators.json").read_text())["actuators"]
    if [a["id"] for a in actuators] != list(range(len(actuators))):
        raise ValueError("actuator index does not match archive columns")
    names = [str(a["name"]) for a in actuators]
    arrays = {key: [] for key in ("time_s", "activation", "force_N")}
    for name in sorted(manifest["artifacts"]):
        if re.fullmatch(r"muscles_\d{3}\.npz", name):
            with np.load(verified(name), allow_pickle=False) as chunk:
                for key, parts in arrays.items():
                    parts.append(chunk[key])
    times, activation, force = (np.concatenate(parts) for parts in arrays.values())
    phase_indices = json.loads(verified("summary.json").read_text())["key_indices"]
    if (activation.shape != force.shape or activation.shape != (len(times), len(names))
        or not all(np.isfinite(a).all() for a in (times, activation, force))
        or not np.all(np.diff(times) > 0)
        or len(phase_indices) != 3 or phase_indices != sorted(set(phase_indices))
        or phase_indices[0] != 0 or phase_indices[-1] != len(times) - 1):
        raise ValueError("unusable phase indices, sample times or actuator arrays")
    groups = {}
    for label, pattern in GROUPS.items():
        ids = [i for i, name in enumerate(names) if re.fullmatch(pattern, name)]
        if not ids:
            raise ValueError(f"source actuator identifiers absent: {label}")
        groups[label] = {
            "source_actuators": [names[i] for i in ids],
            "peak_activation_0_to_1": float(activation[:, ids].max()),
            "peak_abs_force_per_actuator_N": float(np.abs(force[:, ids]).max()),
            "phases": {
                phase: {names[i]: {"activation_0_to_1": float(activation[index, i]),
                                    "signed_actuator_force_N": float(force[index, i])} for i in ids}
                for phase, index in zip(("start", "bottom", "return"), phase_indices, strict=True)
            },
        }
    return {
        "evidence_level": "native_model_output",
        "source_run_id": manifest["run_id"],
        "model": manifest["model"],
        "engine": manifest["engine"],
        "execution": manifest["execution"],
        "scientific_input_sha256": used,
        "phase_source_indices": phase_indices,
        "phase_time_s": times[phase_indices].tolist(),
        "group_definition": GROUPS,
        "limitations": [
            "Peak activation and force can occur at different times and in different source actuators.",
            "Model activation is dimensionless. Human EMG, tissue deformation and regional net muscle force require separate measurements.",
            "The source run used assisted muscle control with external joint control.",
        ],
        "groups": groups,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.run), indent=2, allow_nan=False))
