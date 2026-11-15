"""Literal source-path region membership; no inferred volumetric anatomy."""

import xml.etree.ElementTree as ET

from .registry import home

PATH_LAYERS = {"muscle_paths", "arm_muscles", "lumbar_muscles", "abdominal_muscles", "hand_tendons", "pectoral_muscles"}
CAMERA_REGIONS = {"lumbar": "lumbar_muscles", "abdomen": "abdominal_muscles", "chest": "pectoral_muscles"}
HAND_PREFIXES = ("ECR", "ECU", "FCR", "FCU", "PL_", "FDS", "FDP", "EDC", "EDM", "EIP", "EPL", "EPB", "FPL", "APL")
ABDOMINAL_PREFIXES = ("rect_abd", "EO_", "IO", "TR1_", "TR2_", "TR3_", "TR4_", "TR5_")
LUMBAR_PREFIXES = ("IL_", "LTp", "MF_", "QL_", "multifidus", "Ps_", "LD_")


def path_regions(model):
    arms = set()
    for side in "rl":
        root = ET.parse(home() / f"models/ms_human_700/assets/muscle/Muscle_Arm_{side}.xml")
        arms.update(e.get("name") for e in root.findall("./actuator/*"))
    regions = {}
    for i in range(model.nu):
        name = model.actuator(i).name
        values = []
        if name in arms or name.startswith(("SerrAnt", "trap_")):
            values.append("arm_muscles")
        if name.startswith(("PECM1_", "PECM2_", "PECM3_")):
            values.append("pectoral_muscles")
        if name.startswith(HAND_PREFIXES):
            values.append("hand_tendons")
        if name.startswith(ABDOMINAL_PREFIXES):
            values.append("abdominal_muscles")
        if name.startswith(LUMBAR_PREFIXES):
            values.append("lumbar_muscles")
        regions[name] = values
    return regions


def selected_paths(model, layers):
    regions = path_regions(model)
    requested = PATH_LAYERS - {"muscle_paths"} if "muscle_paths" in layers else set(layers) & PATH_LAYERS
    return {name: memberships for name, memberships in regions.items() if set(memberships) & requested}
