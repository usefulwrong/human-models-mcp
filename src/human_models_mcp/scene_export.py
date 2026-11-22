"""Official MuJoCo USD animation from immutable states, with native double-precision checks."""

import csv
import hashlib
import json
import zipfile

import numpy as np
from .anatomy import CAMERA_REGIONS, PATH_LAYERS, selected_paths

from .catalog import model_card
from .registry import home
from .rendering import write_json


def safe_archive(path):
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
            raise ValueError("trajectory uncompressed size exceeds 64 MiB")
        for info in archive.infolist():
            if not info.filename.endswith(".npy"):
                raise ValueError("unexpected trajectory member")
            with archive.open(info) as stream:
                version = np.lib.format.read_magic(stream)
                reader = (
                    np.lib.format.read_array_header_1_0
                    if version == (1, 0)
                    else np.lib.format.read_array_header_2_0
                )
                shape, _, dtype = reader(stream)
                if dtype.hasobject or np.prod(shape, dtype=object) * dtype.itemsize > 64 * 1024 * 1024:
                    raise ValueError("unbounded or object trajectory array")


def load_saved_run(source):
    """Compile the exact recorded model and verify the saved state layout and clock."""
    import mujoco as mj

    run = json.loads((source / "manifest.json").read_text())
    card = model_card(verify=True, model_id=run["model"]["id"])
    if card.get("status") != "available":
        raise ValueError("pinned model unavailable or hash invalid: " + str(card))
    if run["engine"].get("name") != "mujoco" or run["engine"].get("version") != mj.__version__:
        raise ValueError("incompatible source engine; saved states require the exact recorded MuJoCo version")
    if any(run["model"].get(key) != card[key] for key in ("revision", "asset_sha256")):
        raise ValueError("incompatible source model revision/hash; retargeting is not supported")
    pushup = run["scenario_id"] in ("pushup", "pushup_palms", "pushup_knuckles")
    if pushup:
        from .adapters.pushup import pushup_model

        recipe = json.loads((source / "model_recipe.json").read_text())
        _, model, data = pushup_model(recipe["timestep_s"], recipe["friction"], recipe["muscle_strength_scale"], recipe.get("hand_support", "legacy_point"), recipe.get("support_boundary", "frictional"), recipe["parameters"].get("knuckle_technique", "legacy_flared"), recipe["parameters"].get("palm_technique", "legacy_reach"))
    elif run["scenario_id"] in ("elbow_tracking", "loaded_elbow"):
        from .adapters.loaded import fixture_model

        recipe = {}
        _, model, data, xml = fixture_model(run["execution"]["timestep_s"])
        if hashlib.sha256(xml.encode()).hexdigest() != run["model"]["derivation"]["derived_mjcf_sha256"]:
            raise ValueError("source fixture recipe differs")
    else:
        model = mj.MjModel.from_xml_path(str(home() / "models/ms_human_700/scene_locomotion.xml"))
        data = mj.MjData(model)
        recipe = json.loads((source / "model_recipe.json").read_text())
        model.opt.timestep = recipe["timestep_override_s"]
        model.opt.tolerance, model.opt.iterations = recipe["solver_tolerance"], recipe["solver_iterations"]
    safe_archive(source / "trajectory.npz")
    with np.load(source / "trajectory.npz", allow_pickle=False) as saved:
        state_spec = int(saved["state_spec"])
        states, times, qpos = saved["states"], saved["time_s"], saved["qpos"]
    if state_spec != int(mj.mjtState.mjSTATE_INTEGRATION):
        raise ValueError("only recorded integration states supported")
    if times.ndim != 1 or not 3 <= len(times) <= 401:
        raise ValueError("trajectory requires a one-dimensional clock with 3 to 401 states")
    if states.shape != (len(times), mj.mj_stateSize(model, state_spec)) or qpos.shape != (
        len(times),
        model.nq,
    ):
        raise ValueError("trajectory shapes differ from the pinned compiled model")
    if (
        not all(np.isfinite(v).all() for v in (states, times, qpos))
        or not np.all(np.diff(times) > 0)
    ):
        raise ValueError("nonfinite, nonmonotonic or unsupported state count")
    with (source / "series.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(times) or not np.allclose(
        [float(r["time_s"]) for r in rows], times, rtol=0, atol=1e-12
    ):
        raise ValueError("numeric series and state clock differ")
    return run, model, data, pushup, recipe, states, times, qpos, state_spec, rows


def restore_state(model, data, state, state_spec, qpos, time_s):
    import mujoco as mj

    mj.mj_setState(model, data, state, state_spec)
    mj.mj_forward(model, data)
    if not np.array_equal(data.qpos, qpos) or abs(data.time - time_s) > 1e-12:
        raise ValueError("restored qpos or clock mismatch; no state reintegration permitted")


def export_scene(job):
    import mujoco as mj
    from mujoco.usd.exporter import USDExporter
    from pxr import UsdGeom

    path, request = job["path"], job["record"]["request"]
    source, work = path / "input", path / "work"
    work.mkdir(exist_ok=True)
    run, model, data, pushup, recipe, states, times, qpos, state_spec, rows = load_saved_run(source)
    settings = request["options"]
    indices = np.unique(np.linspace(0, len(times) - 1, settings["frames"], dtype=int))
    if len(indices) != settings["frames"]:
        raise ValueError("requested frames exceed distinct source states")
    layers = request["layers"]
    atlas = None
    atlas_report = None
    rectus_meshes = None
    rectus_frames = []
    phases = {}
    if "pectoralis_atlas" in layers:
        from .atlas import atlas_lock, atlas_lock_digest
        from .atlas_registration import register, skin

        if request["atlas_lock_sha256"] != atlas_lock_digest(atlas_lock()):
            raise ValueError("atlas registration lock changed between submission and rendering")
        mj.mj_forward(model, data)
        atlas = register(model, data, run["model"], source)
        atlas_report = atlas[-1]
        atlas_report["faces"] = atlas[0].tolist()
    elif "rectus_atlas" in layers:
        from .atlas import atlas_lock_digest
        from .rectus import ASSET, SOURCE, register as register_rectus, skin as skin_rectus

        if request["atlas_lock_sha256"] != atlas_lock_digest(SOURCE):
            raise ValueError("rectus registration lock changed between submission and rendering")
        rectus_meshes = register_rectus(source / ASSET, run["model"])
        atlas_report = {
            "status": "illustrative", "source": SOURCE,
            "anatomical_id": "Rectus abdominis muscle (bilateral)",
            "method": "12 mm source vertex caps fitted to pubic and costal sites, proper rotation and axial display scale",
            "activation_mapping": "unavailable; fixed fibre shading with source tendon assignments",
            "structures": {side: {"source_object": f"Rectus abdominis muscle.{side}", "vertices": len(local),
                                  "triangles": len(faces), "tendon_faces": int(tendon.sum()),
                                  "target_sites": [f"rect_abd_{side}-P1", f"rect_abd_{side}-P4"]}
                           for side, (local, _, faces, tendon) in rectus_meshes.items()},
            "thresholds": {"anchor_error_m": 2e-6, "axial_scale": [.73, 1.35],
                           "landmark_distance_m": [.2, .65], "median_signed_lateral_m": ">0"},
            "limitations": ["Endpoint agreement is imposed by the fit. Interior landmarks and human correspondence were not tested.",
                            "Affine geometric animation and source tendon materials provide no tissue stress, strain or activation."],
        }
    if atlas_report or pushup and request.get("recipe"):
        summary = json.loads((source / "summary.json").read_text())
        bottom = summary["key_indices"][1]
        if not 0 < bottom < len(times) - 1:
            raise ValueError("atlas rendering requires an interior bottom frame")
        if bottom not in indices:
            nearest = 1 + int(np.argmin(abs(indices[1:-1] - bottom)))
            indices[nearest] = bottom
            indices.sort()
        phases = {"start": 0, "bottom": bottom, "return": len(times) - 1}
        if atlas_report:
            atlas_report["phase_source_indices"] = phases
    option = mj.MjvOption()
    option.flags[mj.mjtVisFlag.mjVIS_TENDON] = False
    if "bones" in layers and "native_geometry" not in layers:
        model.geom_rgba[
            (model.geom_type != mj.mjtGeom.mjGEOM_MESH) & (model.geom_type != mj.mjtGeom.mjGEOM_PLANE), 3
        ] = 0
    exporter = USDExporter(
        model, width=480, height=480, output_directory="usd", output_directory_root=str(work), verbose=False
    )
    muscle_names = (
        ("BIClong_r", "BICshort_r", "TRIlong_r") if model.nu == 700 else ("recfem_r", "soleus_r", "vasmed_r")
    )
    regions = {}
    if pushup or set(layers) & (PATH_LAYERS - {"muscle_paths"}):
        regions = selected_paths(model, layers)
        muscle_names = list(regions)
    muscles = [
        model.actuator(n) for n in muscle_names if mj.mj_name2id(model, mj.mjtObj.mjOBJ_ACTUATOR, n) >= 0
    ]
    selected = {int(model.actuator_trnid[a.id, 0]): a.id for a in muscles}
    if set(layers) & PATH_LAYERS and not selected:
        raise ValueError("no reviewed muscle path identifiers for this source model")
    model.tendon_group[:] = 5
    for tendon in selected:
        model.tendon_group[tendon] = 0
    paths_option = mj.MjvOption()
    paths_option.tendongroup[:] = [1, 0, 0, 0, 0, 0]
    paths_option.flags[mj.mjtVisFlag.mjVIS_TENDON] = True
    visual = mj.MjvScene(model, maxgeom=20000)
    camera = mj.MjvCamera()
    joint_names = (
        ("elbow_flexion_r",)
        if model.nu == 700
        else ("knee_angle_r", "knee_angle_l", "ankle_angle_r", "ankle_angle_l")
    )
    if pushup:
        joint_names = ("elbow_flexion_r", "elbow_flexion_l", "shoulder_elv_r", "shoulder_elv_l")
        if recipe.get("hand_support", "legacy_point") != "legacy_point":
            joint_names += tuple(name + "_" + side for side in "rl" for name in ("flexion", "deviation", "pro_sup"))
    frames = []
    landmarks = {}
    pelvis = model.body("pelvis").id
    source_support = (
        json.loads((source / "support.json").read_text())["samples"]
        if (source / "support.json").exists()
        else None
    )
    source_wrists = json.loads((source / "wrists.json").read_text())["samples"] if (source / "wrists.json").exists() else None
    previous_atlas = None
    for frame, index in enumerate(indices):
        restore_state(model, data, states[index], state_spec, qpos[index], times[index])
        atlas_fields = {}
        if atlas is not None:
            surface, checks = skin(model, data, atlas)
            checks["max_vertex_motion_since_previous_sample_m"] = (
                None if previous_atlas is None else float(np.linalg.norm(surface - previous_atlas, axis=1).max()))
            previous_atlas = surface
            atlas_fields = {"atlas_vertices_m": surface.tolist(), "atlas_checks": checks}
        elif rectus_meshes is not None:
            surfaces, checks, sites = skin_rectus(model, data, rectus_meshes)
            for side, surface in surfaces.items():
                checks[side]["max_vertex_motion_since_previous_sample_m"] = (
                    float(np.linalg.norm(surface - rectus_frames[-1][side], axis=1).max()) if rectus_frames else None
                )
            rectus_frames.append(surfaces)
            atlas_fields = {"atlas_checks": checks, "rectus_sites_m": sites}
        row = rows[index]
        if pushup:
            if np.any(data.xfrc_applied) or np.any(data.qfrc_applied[:6]):
                raise ValueError("pushup saved state contains prohibited external root support")
            if run["execution"]["parameters"]["control"] == "muscle" and np.any(data.qfrc_applied):
                raise ValueError("muscle-controlled saved state contains external joint forces")
        elif "applied_torque_Nm" in row:
            dof = model.joint("elbow_flexion_r").dofadr[0]
            if abs(data.qfrc_applied[dof] - float(row["applied_torque_Nm"])) > 1e-10:
                raise ValueError("saved applied joint torque differs from restored state")
        else:
            force = np.array([float(row[f"assist_force_{a}_N"]) for a in "xyz"])
            force[2] -= run["model"]["derivation"].get("downward_load_N", 0)
            torque = [float(row[f"assist_torque_{a}_Nm"]) for a in "xyz"]
            if not np.allclose(data.xfrc_applied[pelvis], [*force, *torque], rtol=0, atol=1e-10):
                raise ValueError("saved external support wrench differs from restored state")
        exporter.update_scene(data, scene_option=option)
        geoms = []
        for g in exporter.scene.geoms[: exporter.scene.ngeom]:
            if g.objtype != mj.mjtObj.mjOBJ_GEOM or g.rgba[3] <= 0 or g.type == mj.mjtGeom.mjGEOM_PLANE:
                continue
            gid = int(g.objid)
            name = model.geom(gid).name
            value = {
                "id": gid,
                "name": name,
                "usd_name": exporter._get_geom_name(g),
                "position_m": data.geom_xpos[gid].tolist(),
                "rotation": data.geom_xmat[gid].reshape(3, 3).tolist(),
            }
            if model.geom_type[gid] == mj.mjtGeom.mjGEOM_MESH:
                mesh_id = int(model.geom_dataid[gid])
                face_start = int(model.mesh_faceadr[mesh_id])
                triangles = model.mesh_face[face_start : face_start + int(model.mesh_facenum[mesh_id])]
                valid = [tuple(sorted(map(int, tri))) for tri in triangles if len(set(map(int, tri))) == 3]
                canonical = sorted(set(valid))
                vertex_start = int(model.mesh_vertadr[mesh_id])
                vertex_buffer = model.mesh_vert[
                    vertex_start : vertex_start + int(model.mesh_vertnum[mesh_id])
                ].astype("<f4", copy=True)
                vertex_buffer[vertex_buffer == 0] = 0
                value["surface"] = {
                    "vertices": int(model.mesh_vertnum[mesh_id]),
                    "vertex_coordinates_sha256": hashlib.sha256(vertex_buffer.tobytes()).hexdigest(),
                    "vertex_encoding": "little-endian float32 C-order XYZ, signed zero canonicalized",
                    "source_faces": len(triangles),
                    "distinct_nondegenerate_faces": len(canonical),
                    "repeated_index_faces": len(triangles) - len(valid),
                    "duplicate_faces": len(valid) - len(canonical),
                    "canonical_faces_sha256": hashlib.sha256(
                        json.dumps(canonical, separators=(",", ":")).encode()
                    ).hexdigest(),
                }
            if model.geom_type[gid] == mj.mjtGeom.mjGEOM_MESH and any(
                n in name for n in ("humerus", "ulna", "radius", "r_femur", "l_femur")
            ):
                mid = int(model.geom_dataid[gid])
                adr = int(model.mesh_vertadr[mid])
                n = int(model.mesh_vertnum[mid])
                ids = [0, n // 2, n - 1]
                local = model.mesh_vert[adr : adr + n]
                local_rotation = np.empty(9)
                mj.mju_quat2Mat(local_rotation, model.geom_quat[gid])
                bid = int(model.geom_bodyid[gid])
                value["body"] = {
                    "id": bid,
                    "name": model.body(bid).name,
                    "position_m": data.xpos[bid].tolist(),
                    "rotation": data.xmat[bid].reshape(3, 3).tolist(),
                    "geom_local_position_m": model.geom_pos[gid].tolist(),
                    "geom_local_rotation": local_rotation.reshape(3, 3).tolist(),
                }
                value["landmarks"] = [
                    {
                        "vertex": i,
                        "local_m": local[i].tolist(),
                        "world_m": (
                            data.geom_xpos[gid] + data.geom_xmat[gid].reshape(3, 3) @ local[i]
                        ).tolist(),
                    }
                    for i in ids
                ]
                landmarks[name] = gid
            geoms.append(value)
        paths = []
        if set(layers) & PATH_LAYERS:
            segments = {}
            mj.mjv_updateScene(model, data, paths_option, None, camera, mj.mjtCatBit.mjCAT_ALL, visual)
            for g in visual.geoms[: visual.ngeom]:
                if g.objtype != mj.mjtObj.mjOBJ_TENDON or g.objid not in selected:
                    continue
                aid = selected[g.objid]
                segment = segments.get(int(g.objid), 0)
                segments[int(g.objid)] = segment + 1
                act = int(model.actuator_actadr[aid])
                if act < 0:
                    raise ValueError("selected path has no recorded muscle activation")
                direction = g.mat.reshape(3, 3)[:, 2] * g.size[2]
                paths.append(
                    {
                        "tendon_id": int(g.objid),
                        "actuator": model.actuator(aid).name,
                        "segment": segment,
                        "regions": regions.get(model.actuator(aid).name, []),
                        "start_m": (g.pos - direction).tolist(),
                        "end_m": (g.pos + direction).tolist(),
                        "radius_m": float(g.size[0]),
                        "display_radius_m": .0007 if pushup and "hand_tendons" in regions[model.actuator(aid).name] else .0012 if pushup else max(float(g.size[0]), .001),
                        "activation": float(data.act[act]),
                    }
                )
        axes = []
        for name in joint_names:
            jid = model.joint(name).id
            axes.append(
                {
                    "joint": name,
                    "origin_m": data.xanchor[jid].tolist(),
                    "world_axis": data.xaxis[jid].tolist(),
                }
            )
        contact = None
        if source_support:
            contact = source_support[index]
            center = np.array(contact["com_world_m"])
            if np.linalg.norm(center - data.subtree_com[pelvis]) > 1e-10:
                raise ValueError("saved contact COM differs from restored state")
            ground = np.zeros(3)
            floor = model.geom("floor").id
            for i in range(data.ncon):
                c = data.contact[i]
                if floor in c.geom:
                    wrench = np.zeros(6)
                    mj.mj_contactForce(model, data, i, wrench)
                    ground += (1 if c.geom[0] == floor else -1) * c.frame.reshape(3, 3).T @ wrench[:3]
            if pushup and recipe.get("support_boundary") == "fixed_points":
                from .adapters.supports import fixed_reactions
                for reaction in fixed_reactions(mj, model, data):
                    ground += reaction["force_world_N"]
            if np.linalg.norm(ground - [float(rows[index][f"grf_{a}_N"]) for a in "xyz"]) > 1e-6:
                raise ValueError("saved contact force differs from restored state")
        if source_wrists:
            from .adapters.hands import measure_wrists
            _, restored = measure_wrists(mj, model, data, recipe["hand_support"])
            for actual, measured in zip(restored, source_wrists[index]["hands"], strict=True):
                for key in ("force_world_N", "ground_moment_about_wrist_Nm", "wrist_origin_m"):
                    if not np.allclose(actual[key], measured[key], rtol=0, atol=1e-6):
                        raise ValueError("saved wrist measurement differs from restored state: " + key)
        frames.append(
            {
                **atlas_fields,
                "frame": frame,
                "source_index": int(index),
                "time_s": float(data.time),
                "state_sha256": hashlib.sha256(states[index].tobytes()).hexdigest(),
                "geoms": geoms,
                "paths": paths,
                "joint_axes": axes,
                "com_world_m": data.subtree_com[pelvis].tolist(),
                "pelvis_com_world_m": data.xipos[pelvis].tolist(),
                "contact": contact,
                "metrics": rows[index],
                "hands": source_wrists[index]["hands"] if source_wrists else [],
                "hand_pads": [{"name": model.geom(g).name, "position_m": data.geom_xpos[g].tolist(),
                               "radius_m": float(model.geom_size[g, 0])} for g in range(model.ngeom)
                              if model.geom(g).name.startswith("palm_")],
            }
        )
    normalization = []
    for prim in exporter.stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        counts = list(mesh.GetFaceVertexCountsAttr().Get())
        if any(n != 3 for n in counts):
            raise ValueError("only source triangles are supported")
        faces = np.array(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32).reshape(-1, 3)
        seen = set()
        keep = []
        for i, tri in enumerate(faces):
            key = tuple(sorted(map(int, tri)))
            if len(set(key)) == 3 and key not in seen:
                seen.add(key)
                keep.append(i)
        if len(keep) != len(faces):
            mesh.GetFaceVertexIndicesAttr().Set(faces[keep].reshape(-1).tolist())
            mesh.GetFaceVertexCountsAttr().Set([3] * len(keep))
            for variable in UsdGeom.PrimvarsAPI(mesh).GetPrimvars():
                if variable.GetInterpolation() != UsdGeom.Tokens.faceVarying:
                    continue
                if variable.IsIndexed():
                    indices_uv = np.asarray(variable.GetIndices())
                    if len(indices_uv) == len(faces) * 3:
                        variable.SetIndices(indices_uv.reshape(len(faces), 3)[keep].reshape(-1).tolist())
                else:
                    values_uv = np.asarray(variable.Get())
                    if len(values_uv) == len(faces) * 3:
                        variable.Set(
                            values_uv.reshape((len(faces), 3) + values_uv.shape[1:])[keep]
                            .reshape((-1,) + values_uv.shape[1:])
                            .tolist()
                        )
            normalization.append(
                {
                    "prim": str(prim.GetPath()),
                    "source_triangles": len(faces),
                    "removed_repeated_index_or_duplicate_faces": len(faces) - len(keep),
                    "geometry_effect": "No vertex or distinct nondegenerate triangle changed; visual-import compatibility only",
                }
            )
    UsdGeom.SetStageMetersPerUnit(exporter.stage, 1.0)
    exporter.stage.SetTimeCodesPerSecond(settings["fps"])
    exporter.save_scene("usdc")
    exporter.stage.SetEndTimeCode(len(frames) - 1)
    usd = work / "usd/frames" / f"frame_{len(frames)}.usdc"
    exporter.stage.Export(str(usd))
    expected = {
        "schema_version": "1.0",
        "scenario_id": run["scenario_id"],
        "pushup": pushup,
        "acceptance": run.get("scientific", {}).get("acceptance", {}),
        "path_inventory": {"selected_actuators": muscle_names, "selected_count": len(muscle_names),
                           "coverage": "all available paths in requested native regions" if pushup else "legacy selected paths"},
        "run_id": run["run_id"],
        "model": run["model"],
        "engine": run["engine"],
        "units": {"length": "m", "angle": "rad", "force": "N", "torque": "N*m", "activation": "1"},
        "coordinates": "right-handed world Z-up; identity map to Blender; metresPerUnit=1",
        "exporter": "mujoco.usd.exporter.USDExporter 3.17.0",
        "mesh_normalization": normalization,
        "usd_file": str(usd.relative_to(work)),
        "timing": {
            "fps": settings["fps"],
            "source_duration_s": float(times[-1] - times[0]),
            "video_duration_s": len(frames) / settings["fps"],
            "interpolation": "no interpolated physics states; explicit source indices; final frame held one video interval",
        },
        "phase_source_indices": phases,
        "geometry_validation": {
            "translation_tolerance_m": 2e-6,
            "rotation_matrix_tolerance": 2e-6,
            "landmark_tolerance_m": 3e-6,
            "landmark_geometries": landmarks,
        },
        "source_files": job["record"]["source_files"],
        "request": request,
        "regional_layer": CAMERA_REGIONS.get(settings["camera_view"]),
        "frames": frames,
        **({"atlas": atlas_report} if atlas_report else {}),
    }
    if rectus_meshes is not None:
        arrays = {}
        for side, (_, _, faces, tendon) in rectus_meshes.items():
            arrays[f"{side}_vertices"] = np.stack([frame[side] for frame in rectus_frames]).astype("float32")
            arrays[f"{side}_faces"] = faces
            arrays[f"{side}_tendon"] = tendon
        np.savez_compressed(work / "atlas_surfaces.npz", **arrays)
    write_json(work / "expected.json", expected)
    return expected
