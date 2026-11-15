"""Independent native MuJoCo check of downloaded source states and exported references."""

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
import numpy as np
import mujoco as mj
from PIL import Image

folder = Path(sys.argv[1])
output = folder / "unpacked"
output.mkdir(exist_ok=True)
for name, subdir in [("source.zip", "source"), ("scene.zip", "scene")]:
    destination = output / subdir
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(folder / name) as archive:
        for item in archive.infolist():
            if Path(item.filename).is_absolute() or ".." in Path(item.filename).parts:
                raise ValueError("unsafe scene archive")
        archive.extractall(destination)
source = output / "source"
run = json.loads((source / "manifest.json").read_text())
expected = json.loads((output / "scene/expected.json").read_text())
for name, sha in expected["source_files"].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == sha
root = Path("/app/models/ms_human_700")
if run["scenario_id"] in ("pushup", "pushup_palms", "pushup_knuckles"):
    recipe = json.loads((source / "model_recipe.json").read_text())
    spec = mj.MjSpec.from_file(str(root / "MS-Human-700.xml"))
    if recipe.get("hand_support", "legacy_point") != "legacy_point":
        from human_models_mcp.adapters.hands import configure_hands
        spec, _ = configure_hands(spec, recipe["hand_support"])
    spec.option.timestep = recipe["timestep_s"]
    spec.option.integrator = mj.mjtIntegrator.mjINT_IMPLICITFAST
    spec.option.tolerance, spec.option.iterations = 1e-10, 100
    friction = recipe["friction"]
    spec.worldbody.add_geom(name="floor", type=mj.mjtGeom.mjGEOM_PLANE, size=[3, 3, .1],
                            contype=4, conaffinity=2, friction=[friction, .005, .0001], solref=[.01, 1],
                            rgba=[.15, .18, .23, 1])
    for pad in json.loads((source / "contact_map.json").read_text())["pads"]:
        if spec.geom(pad["name"]) is not None:
            continue
        spec.body(pad["body"]).add_geom(name=pad["name"], type=mj.mjtGeom.mjGEOM_SPHERE,
            pos=pad["pos_m"], size=[pad["radius_m"], 0, 0], mass=0, contype=2, conaffinity=4,
            friction=[friction, .005, .0001], solref=[.01, 1], rgba=[.1, .6, .7, .6])
    if recipe.get("support_boundary") == "fixed_points":
        from human_models_mcp.adapters.supports import install_fixed_supports
        install_fixed_supports(mj, spec, recipe["fixed_supports"])
    if recipe["parameters"].get("palm_technique") == "chest_full":
        derivation = recipe["wrist_range_derivation"]
        assert derivation["changed_limits_rad"] == {"flexion_r": [-.930016, .6], "flexion_l": [-.930016, .6]}
        assert derivation["reference_asset_sha256"] == "a4ea41d27ebcca8fc71c065587b1895325dad0f97ee1e01b9719ed57ee8423c6"
        # Early snapshots contain the complete reference.npz and pinned recipe, before the auxiliary JSON was exported.
        reference_input = source / "palm_reference_input.json"
        if reference_input.exists():
            assert hashlib.sha256(reference_input.read_bytes()).hexdigest() == derivation["reference_asset_sha256"]
        for name, limits in derivation["changed_limits_rad"].items():
            spec.joint(name).range[:] = limits
    model = spec.compile()
    if recipe.get("support_boundary") == "fixed_points":
        for g in range(model.ngeom):
            if model.geom(g).name == "floor" or model.geom(g).name.startswith(("palm_", "toe_")):
                model.geom_solref[g] = [.004, 1]
                model.geom_solimp[g, :2] = [.95, .99]
                model.geom_margin[g] = 0
        model.opt.jacobian = mj.mjtJacobian.mjJAC_DENSE
        model.eq_solref[model.eq_type == mj.mjtEq.mjEQ_JOINT] = [.004, 1]
        model.eq_solimp[model.eq_type == mj.mjtEq.mjEQ_JOINT, :2] = [.9999, .9999]
    for g in range(model.ngeom):
        if model.geom(g).name.startswith("palm_"):
            model.geom_friction[g, 0] = friction
    model.dof_damping[6:85] = np.maximum(model.dof_damping[6:85], recipe["passive_damping_floor"])
    model.actuator_gainprm[:, 2] *= recipe["muscle_strength_scale"]
    model.actuator_biasprm[:, 2] *= recipe["muscle_strength_scale"]
    assert model.nu == 700 and model.neq == 42 + len(recipe.get("fixed_supports", []))
elif run["model"]["id"] == "ms_human_700":
    spec = mj.MjSpec.from_file(str(root / "MS-Human-700.xml"))
    spec.option.timestep = run["execution"]["timestep_s"]
    base = spec.compile()
    initial = mj.MjData(base)
    mj.mj_resetDataKeyframe(base, initial, 0)
    mj.mj_forward(base, initial)
    eq = spec.add_equality(
        name="fixture_pelvis",
        type=mj.mjtEq.mjEQ_WELD,
        objtype=mj.mjtObj.mjOBJ_BODY,
        name1="pelvis",
        name2="world",
    )
    eq.data[:3] = initial.xpos[base.body("pelvis").id]
    eq.solref[:] = [0.02, 1]
    eq.solimp[:] = [0.95, 0.95, 0.001, 0.5, 2]
    model = spec.compile()
else:
    model = mj.MjModel.from_xml_path(str(root / "scene_locomotion.xml"))
data = mj.MjData(model)
archive = np.load(source / "trajectory.npz", allow_pickle=False)
stationarity = None
if run["scenario_id"] in ("pushup_palms", "pushup_knuckles") and recipe.get("support_boundary") == "fixed_points":
    pads = [i for i in range(model.ngeom) if model.geom(i).name.startswith(("palm_", "toe_"))]
    recorded = json.loads((source / "support_stationarity.json").read_text())
    drift = np.zeros(len(pads))
    technique = []
    for index, state in enumerate(archive["states"]):
        mj.mj_setState(model, data, state, int(archive["state_spec"]))
        mj.mj_forward(model, data)
        if index == 0:
            initial = data.geom_xpos[pads, :2].copy()
        drift = np.maximum(drift, np.linalg.norm(data.geom_xpos[pads, :2] - initial, axis=1))
        if recipe["parameters"].get("palm_technique") in ("chest_level", "chest_full"):
            from human_models_mcp.adapters.hands import measure_palm_technique, palm_placement_passes
            assert palm_placement_passes([measure_palm_technique(model, data)])
        if recipe["parameters"].get("palm_technique") == "chest_full":
            from human_models_mcp.adapters.hands import wrist_shaft_extension
            assert max(wrist_shaft_extension(model, data, s) for s in "rl") <= np.pi / 2 + .01
            if index in (0, len(archive["states"]) - 1):
                assert max(data.qpos[model.joint("elbow_flexion_" + s).id] for s in "rl") < .15
        if recipe["parameters"].get("knuckle_technique") == "neutral_tucked":
            from human_models_mcp.adapters.hands import measure_knuckle_technique
            measured = measure_knuckle_technique(model, data)
            if data.time >= .2 - 1e-10:
                for side in "rl":
                    assert measured[f"hand_{side}_palm_inward_cosine"] > np.cos(np.pi / 6)
                    assert measured[f"hand_{side}_radial_forward_cosine"] > np.cos(np.pi / 6)
                    if data.qpos[model.joint("elbow_flexion_" + side).id] > .6:
                        assert measured[f"elbow_{side}_flare_rad"] < np.pi / 6
            technique.append(measured)
    assert max(drift) < recorded["displacement_tolerance_m"] == .0005
    assert all(d <= recorded["max_contact_patch_displacement_by_pad_m"][model.geom(g).name] + 1e-12
               for g, d in zip(pads, drift, strict=True))
    wrist_motion = float(np.ptp(archive["qpos"][:, model.jnt_qposadr[model.joint("flexion_r").id]]))
    wrist_ranges = {n: float(np.ptp(archive["qpos"][:, model.jnt_qposadr[model.joint(n + "_r").id]]))
                    for n in ("flexion", "deviation", "pro_sup")}
    assert max(wrist_ranges.values()) > .01
    stationarity = {"all_saved_states": len(archive["states"]), "pad_count": len(pads),
                    "max_pad_displacement_m": float(max(drift)), "wrist_motion_rad": wrist_motion,
                    "native_right_wrist_coordinate_ranges_rad": wrist_ranges,
                    "tolerance_m": .0005, "status": "pass"}
    if recipe["parameters"].get("palm_technique") in ("chest_level", "chest_full"):
        stationarity["chest_level_palms_all_saved_states"] = "pass"
    if technique:
        bottom = json.loads((source / "summary.json").read_text())["key_indices"][1]
        assert all(technique[bottom][f"shoulder_{s}_above_elbow_m"] < .05 for s in "rl")
        stationarity["neutral_tucked_technique_all_saved_states"] = "pass"
transferred = json.loads((folder / "frames.json").read_text())
with (source / "series.csv").open() as stream:
    rows = list(csv.DictReader(stream))
with zipfile.ZipFile(folder / "frames.zip") as images:
    assert len(images.namelist()) == len(transferred["frames"]) == len(expected["frames"])
    for frame, reference in zip(transferred["frames"], expected["frames"]):
        index = frame["source_index"]
        assert (
            frame["time_s"]
            == float(archive["time_s"][index])
            == float(rows[index]["time_s"])
            == reference["time_s"]
        )
        assert (
            frame["state_sha256"]
            == hashlib.sha256(archive["states"][index].tobytes()).hexdigest()
            == reference["state_sha256"]
        )
        png = images.read(f"frame_{frame['frame']:04d}.png")
        assert hashlib.sha256(png).hexdigest() == frame["png_sha256"]
        with Image.open(io.BytesIO(png)) as image:
            image.verify()
assert (
    hashlib.sha256((folder / "preview.png").read_bytes()).hexdigest()
    == transferred["frames"][-1]["png_sha256"]
)
with Image.open(folder / "animation.gif") as gif:
    assert gif.n_frames == len(transferred["frames"])
    for index in range(gif.n_frames):
        gif.seek(index)
        assert gif.info["duration"] == transferred["timing"]["gif_frame_interval_ms"]

maxp = maxr = 0
for index in (0, len(expected["frames"]) // 2, len(expected["frames"]) - 1):
    frame = expected["frames"][index]
    mj.mj_setState(model, data, archive["states"][frame["source_index"]], int(archive["state_spec"]))
    mj.mj_forward(model, data)
    assert np.array_equal(data.qpos, archive["qpos"][frame["source_index"]])
    assert abs(data.time - frame["time_s"]) < 1e-12
    if run["scenario_id"] in ("pushup", "pushup_palms", "pushup_knuckles"):
        assert not np.any(data.xfrc_applied) and not np.any(data.qfrc_applied[:6])
        if run["execution"]["parameters"]["control"] == "muscle":
            assert not np.any(data.qfrc_applied)
        for path in frame["paths"]:
            aid = model.actuator(path["actuator"]).id
            assert abs(path["activation"] - data.act[model.actuator_actadr[aid]]) < 1e-12
        if (source / "pectorals.csv").exists():
            with (source / "pectorals.csv").open() as stream:
                pectorals = [r for r in csv.DictReader(stream) if int(r["sample"]) == frame["source_index"]]
            assert len(pectorals) == 6
            for entry in pectorals:
                aid = model.actuator(entry["actuator"]).id
                assert abs(float(entry["activation"]) - data.act[model.actuator_actadr[aid]]) < 1e-12
                assert abs(float(entry["force_N"]) - data.actuator_force[aid]) < 1e-8
                assert abs(float(entry["power_W"]) - data.actuator_force[aid] * data.actuator_velocity[aid]) < 1e-8
    for g in frame["geoms"]:
        gid = g["id"]
        assert model.geom(gid).name == g["name"]
        p = np.max(abs(data.geom_xpos[gid] - g["position_m"]))
        rot = np.max(abs(data.geom_xmat[gid].reshape(3, 3) - g["rotation"]))
        maxp = max(maxp, float(p))
        maxr = max(maxr, float(rot))
        assert p < 1e-12 and rot < 1e-12
        for landmark in g.get("landmarks", []):
            mid = int(model.geom_dataid[gid])
            v = model.mesh_vert[model.mesh_vertadr[mid] + landmark["vertex"]]
            world = data.geom_xpos[gid] + data.geom_xmat[gid].reshape(3, 3) @ v
            assert np.linalg.norm(world - landmark["world_m"]) < 1e-12
result = {
    "status": "pass",
    "method": "Public MuJoCo reconstruction of transferred NPZ, fixture recipe and mesh landmarks; no scenario/controller execution or mj_step. Detailed hands share the source-hand derivation helper; engine/state/mesh comparisons are independent of Blender.",
    "max_native_reference_position_error_m": maxp,
    "max_native_reference_rotation_error": maxr,
    "checked_frames": [0, len(expected["frames"]) // 2, len(expected["frames"]) - 1],
    "all_frame_state_csv_png_hashes": "pass",
    "gif_clock_verified": "pass",
    "stationary_supports": stationarity,
}
(folder / "independent-native.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
