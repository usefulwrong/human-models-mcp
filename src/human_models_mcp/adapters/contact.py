"""Native locomotion contacts and declared external support, not human balance."""

import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from ..registry import ContactParameters, AssistedContactParameters, ContactValidation, home
from ..results import error
from .mujoco import load

MODEL_ID = "ms_human_700_locomotion"


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def hull_xy(points):
    points = sorted(set(tuple(map(float, p[:2])) for p in points))
    if len(points) < 3:
        return [list(p) for p in points], 0.0
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    chains = []
    for ordered in (points, points[::-1]):
        chain = []
        for p in ordered:
            while len(chain) >= 2 and cross(chain[-2], chain[-1], p) <= 0:
                chain.pop()
            chain.append(p)
        chains.extend(chain[:-1])
    area = abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(chains, chains[1:]+chains[:1]))) / 2
    return [list(p) for p in chains], area


def inside_hull(point, polygon, area):
    return area > 1e-10 and all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) >= -1e-10
                              for a, b in zip(polygon, polygon[1:]+polygon[:1]))


def contact_map(m):
    geoms = [{"id": i, "name": m.geom(i).name, "body": m.body(int(m.geom_bodyid[i])).name,
              "type": int(m.geom_type[i]), "contype": int(m.geom_contype[i]), "conaffinity": int(m.geom_conaffinity[i]),
              "condim": int(m.geom_condim[i]), "margin_m": float(m.geom_margin[i]),
              "friction": m.geom_friction[i].tolist(), "solref": m.geom_solref[i].tolist(), "solimp": m.geom_solimp[i].tolist()}
             for i in range(m.ngeom) if m.geom_contype[i] or m.geom_conaffinity[i]]
    exclusions = [dict(e.attrib) for e in ET.parse(home() / "models/ms_human_700/assets/contact/Contact_Lowerbody.xml").findall("./contact/exclude")]
    return {"model_id": MODEL_ID, "collision_geometries": geoms, "excluded_body_pairs": exclusions,
            "disabled_collision_geometries_count": m.ngeom-len(geoms), "explicit_contact_pairs_count": m.npair,
            "note": "Native bitmask/filter/exclusion rules retained. Bone/wrapping visual meshes mostly have collision disabled. Capsule contacts are not complete tissue self-collision."}


def shift_root(mj, m, d, vector, *, velocity=False):
    pelvis = m.body("pelvis").id
    joints = [j for j in range(m.njnt) if m.jnt_bodyid[j] == pelvis and m.jnt_type[j] == mj.mjtJoint.mjJNT_SLIDE]
    components = np.linalg.solve(d.xaxis[joints].T, vector)
    for j, value in zip(joints, components, strict=True):
        if velocity:
            d.qvel[m.jnt_dofadr[j]] += value
        else:
            d.qpos[m.jnt_qposadr[j]] += value
    return [{"joint": m.joint(j).name, "world_axis": d.xaxis[j].tolist(), "increment": float(v)}
            for j, v in zip(joints, components, strict=True)]


def initialize(p):
    mj, m, d = load(model_id=MODEL_ID)
    m.opt.timestep, m.opt.tolerance, m.opt.iterations = p.timestep_s, 1e-12, 200
    pelvis, floor = m.body("pelvis").id, m.geom("floor").id
    feet = [i for i in range(m.ngeom) if m.geom(i).name.startswith(("calcn_skin", "toes_skin"))]
    original = d.qpos.copy()
    if len(feet) != 10 or m.neq != 16 or any(m.eq_type != mj.mjtEq.mjEQ_JOINT) or m.nu != 100 or any(m.actuator_trntype != mj.mjtTrn.mjTRN_TENDON):
        raise ValueError("expected the pinned locomotion foot capsules and sixteen internal joint equalities")
    coupled = []
    for eq in range(m.neq):
        child, parent = int(m.eq_obj1id[eq]), int(m.eq_obj2id[eq])
        if parent < 0 or m.jnt_bodyid[child] == pelvis:
            raise ValueError("world/root equality is outside the contact experiment")
        q = d.qpos[m.jnt_qposadr[parent]] - m.qpos0[m.jnt_qposadr[parent]]
        d.qpos[m.jnt_qposadr[child]] = m.qpos0[m.jnt_qposadr[child]] + np.polynomial.polynomial.polyval(q, m.eq_data[eq, :5])
        coupled.append(m.equality(eq).name)
    mj.mj_forward(m, d)
    gap = min(mj.mj_geomDistance(m, d, i, floor, 1, None) for i in feet)
    shifts = shift_root(mj, m, d, np.array([0, 0, .0002-gap+p.root_height_offset_m]))
    d.qvel[:], d.act[:], d.ctrl[:] = 0, 0, 0
    shift_root(mj, m, d, np.array([p.initial_velocity_x_m_per_s, 0, 0]), velocity=True)
    mj.mj_forward(m, d)
    initial = {"source_keyframe": "init", "source_qpos": original.tolist(), "qpos": d.qpos.tolist(), "qvel": d.qvel.tolist(),
               "muscle_excitations": "all zero; passive muscle forces remain", "muscle_activation": "all zero initially",
               "coupled_equalities": coupled, "pre_alignment_min_sole_gap_m": float(gap), "root_translation_adjustments": shifts,
               "nominal_min_sole_gap_m": .0002, "root_height_offset_m": p.root_height_offset_m,
               "initial_root_origin_world_m": d.xpos[pelvis].tolist(), "initial_pelvis_com_world_m": d.xipos[pelvis].tolist(),
               "initial_com_world_m": d.subtree_com[pelvis].tolist(), "gravity_m_per_s2": m.opt.gravity.tolist(),
               "downward_load_N": p.downward_load_N, "floor": "upstream plane z=0", "no_added_weld_or_kinematic_support": True,
               "initial_contact_semantics": "Bilateral candidates within native contact margins; not initialized at load-bearing equilibrium. Actual force-bearing contacts must occur during the run."}
    return mj, m, d, pelvis, floor, feet, initial


def kinematic_maps(mj, m, d, pelvis):
    linear, angular = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    mj.mj_jacSubtreeCom(m, d, linear, pelvis)
    mj.mj_angmomMat(m, d, angular, pelvis)
    return linear, angular


def momentum_rates(mj, m, d, scratch, pelvis, h):
    linear, angular = kinematic_maps(mj, m, d, pelvis)
    probes = []
    for sign in (-1, 1):
        scratch.qpos[:] = d.qpos
        mj.mj_integratePos(m, scratch.qpos, d.qvel, sign*h)
        mj.mj_kinematics(m, scratch)
        mj.mj_comPos(m, scratch)
        probes.append(kinematic_maps(mj, m, scratch, pelvis))
    a = linear @ d.qacc + (probes[1][0]-probes[0][0]) @ d.qvel/(2*h)
    hdot = angular @ d.qacc + (probes[1][1]-probes[0][1]) @ d.qvel/(2*h)
    return a, hdot, linear @ d.qvel


def controller(mj, m, d, pelvis, origin, orientation, scale):
    jlin, jrot = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    mj.mj_jacBodyCom(m, d, jlin, jrot, pelvis)
    velocity, omega = jlin @ d.qvel, jrot @ d.qvel
    local_error = np.zeros(3)
    mj.mju_subQuat(local_error, orientation, d.xquat[pelvis])
    world_error = d.xmat[pelvis].reshape(3, 3) @ local_error
    force = scale*(3000*(origin-d.xipos[pelvis])-300*velocity) + np.array([0, 0, .25*mj.mj_getTotalmass(m)*9.81])
    torque = scale*(1000*world_error-100*omega)
    return np.clip(force, -1000, 1000), np.clip(torque, -200, 200), velocity, omega


def measure_contacts(mj, m, d, floor, sample, allowed_prefixes=("calcn_skin", "toes_skin")):
    force, moment, points, records = np.zeros(3), np.zeros(3), [], []
    friction_error = 0.0
    for i in range(d.ncon):
        c = d.contact[i]
        local = np.zeros(6)
        mj.mj_contactForce(m, d, i, local)
        rotation = c.frame.reshape(3, 3)
        # The documented wrench acts on geom[1]; frame axes are stored as rows.
        world_force, world_torque = rotation.T @ local[:3], rotation.T @ local[3:]
        floor_contact = floor in c.geom
        other = int(c.geom[1] if c.geom[0] == floor else c.geom[0])
        sign = 1 if c.geom[0] == floor else -1
        if floor_contact:
            if not m.geom(other).name.startswith(allowed_prefixes):
                raise ValueError("non-foot floor contact is outside this bounded stance probe")
            if c.dim != 3:
                raise ValueError("expected native condim=3 foot contact")
            force += sign*world_force
            moment += np.cross(c.pos-d.subtree_com[m.body("pelvis").id], sign*world_force) + sign*world_torque
            if local[0] > 1e-6:
                points.append(c.pos.copy())
        if c.dim == 3 and c.efc_address >= 0:
            friction_error = max(friction_error, abs(local[1])/c.friction[0]+abs(local[2])/c.friction[1]-local[0], -local[0])
        records.append({"sample": sample, "time_s": float(d.time), "contact": i, "geom0": int(c.geom[0]), "geom1": int(c.geom[1]),
                        "gap_m": float(c.dist), "inclusion_margin_m": float(c.includemargin), "active": int(c.efc_address >= 0),
                        "floor_contact": int(floor_contact), "position_m": c.pos.tolist(), "frame_rows": rotation.tolist(),
                        "local_force_N": local[:3].tolist(), "local_torque_Nm": local[3:].tolist(),
                        "force_on_geom1_world_N": world_force.tolist(), "torque_on_geom1_world_Nm": world_torque.tolist(),
                        "normal_force_N": float(local[0]), "friction": c.friction.tolist()})
    polygon, area = hull_xy(points)
    origin_moment = moment + np.cross(d.subtree_com[m.body("pelvis").id], force)
    cop = [-origin_moment[1]/force[2], origin_moment[0]/force[2]] if force[2] > 1e-6 else None
    return force, moment, records, {"sample": sample, "time_s": float(d.time), "polygon_xy_m": polygon, "area_m2": area,
        "com_world_m": d.subtree_com[m.body("pelvis").id].tolist(), "cop_xy_m": cop,
        "com_projection_inside": inside_hull(d.subtree_com[m.body("pelvis").id], polygon, area),
        "cop_inside": inside_hull(cop, polygon, area) if cop else None}, friction_error


def simulate_contact(params: dict, output: Path, validation: dict, *, assisted=False):
    p = (AssistedContactParameters if assisted else ContactParameters).model_validate(params)
    rules = ContactValidation.model_validate(validation).checks
    mj, m, d, pelvis, floor, feet, initial = initialize(p)
    mass = float(mj.mj_getTotalmass(m))
    origin, orientation = d.xipos[pelvis].copy(), d.xquat[pelvis].copy()
    recipe = {"version": "1.0.0", "source_variant": "locomotion", "source_scene": "scene_locomotion.xml", "upstream_floor": True,
              "collision_geometries_changed": False, "added_equalities": 0, "timestep_override_s": p.timestep_s,
              "solver_tolerance": m.opt.tolerance, "solver_iterations": m.opt.iterations,
              "solver": mj.mjtSolver(int(m.opt.solver)).name, "cone": mj.mjtCone(int(m.opt.cone)).name,
              "initialization": "Sixteen source knee equalities, then world-z root translation to 0.2 mm minimum sole clearance plus stated offset; no pose overwrite during integration.",
              "support": "explicit world-frame wrench at pelvis COM" if assisted else "none; passive contact transient", "downward_load_N": p.downward_load_N,
              "controller": {"type": "pelvis_world_pd", "translation_kp_N_per_m": 3000, "translation_kd_Ns_per_m": 300,
                             "rotation_kp_Nm_per_rad": 1000, "rotation_kd_Nms_per_rad": 100,
                             "gain_scale": getattr(p, "assist_gain_scale", 0), "vertical_feedforward_fraction_of_weight": .25,
                             "per_component_force_limit_N": 1000, "per_component_torque_limit_Nm": 200,
                             "target_pelvis_com_world_m": origin.tolist(), "target_quaternion_wxyz": orientation.tolist(),
                             "sampling": "torque/force recorded at a state acts over the following Euler interval"} if assisted else None}
    mapping = contact_map(m)
    dump(output / "model_recipe.json", recipe)
    dump(output / "initial_conditions.json", initial)
    dump(output / "contact_map.json", mapping)
    dump(output / "trajectory_metadata.json", {
        "model_id": MODEL_ID, "artifact": "trajectory.npz", "time_s_unit": "s",
        "states": "Opaque mjSTATE_INTEGRATION layout; mixed units, restore with mj_setState and recorded state_spec, never interpret as one physical quantity.",
        "coordinates": [{"joint": m.joint(j).name, "qpos_index": int(m.jnt_qposadr[j]), "dof_index": int(m.jnt_dofadr[j]),
                         "qpos_unit": "m" if m.jnt_type[j] == mj.mjtJoint.mjJNT_SLIDE else "rad",
                         "qvel_unit": "m/s" if m.jnt_type[j] == mj.mjtJoint.mjJNT_SLIDE else "rad/s",
                         "qacc_unit": "m/s2" if m.jnt_type[j] == mj.mjtJoint.mjJNT_SLIDE else "rad/s2",
                         "generalized_force_unit": "N" if m.jnt_type[j] == mj.mjtJoint.mjJNT_SLIDE else "N*m",
                         "limited": bool(m.jnt_limited[j]), "range": m.jnt_range[j].tolist()} for j in range(m.njnt)],
        "generalized_force_arrays": ["qfrc_constraint", "qfrc_actuator", "qfrc_passive", "qfrc_applied"],
        "actuator_order": [m.actuator(i).name for i in range(m.nu)], "actuator_force_unit": "N",
        "actuator_force_definition": "Signed native tendon-transmission force, not measured biological tension or joint reaction.",
        "ctrl_unit": "1 (muscle excitation)", "act_unit": "1 (muscle activation)",
        "body_order": [m.body(i).name for i in range(m.nbody)],
        "xfrc_applied": "World XYZ force [N] followed by XYZ torque [N*m], applied at each body COM; distinct from MuJoCo torque-first spatial arrays."})
    gap = min(mj.mj_geomDistance(m, d, i, floor, 1, None) for i in feet)
    sides = {m.geom(int(c.geom[1] if c.geom[0] == floor else c.geom[0])).name[-1] for c in d.contact if floor in c.geom}
    if gap < -1e-7:
        return error("invalid_input", f"initial foot penetration {gap:.9g} m; nonpenetrating initial state required")
    if sides != {"r", "l"}:
        return error("invalid_input", f"initial bilateral foot-floor contacts absent; min geometric gap {gap:.9g} m")
    scratch = mj.MjData(m)
    rows, states, qpos, qvel, contacts, support = [], [], [], [], [], []
    vectors = {key: [] for key in ("qacc", "qfrc_constraint", "qfrc_actuator", "qfrc_passive", "qfrc_applied", "actuator_force", "ctrl", "act", "xfrc_applied")}
    state_spec = mj.mjtState.mjSTATE_INTEGRATION
    state = np.empty(mj.mj_stateSize(m, state_spec))
    failure = None
    for step in range(p.steps+1):
        if step:
            mj.mj_step(m, d)
        mj.mj_forward(m, d)
        jlin, jrot = np.zeros((3, m.nv)), np.zeros((3, m.nv))
        mj.mj_jacBodyCom(m, d, jlin, jrot, pelvis)
        velocity, omega = jlin @ d.qvel, jrot @ d.qvel
        assist_force, assist_torque = np.zeros(3), np.zeros(3)
        if assisted:
            assist_force, assist_torque, velocity, omega = controller(mj, m, d, pelvis, origin, orientation, p.assist_gain_scale)
        load_force = np.array([0, 0, -p.downward_load_N])
        d.xfrc_applied[pelvis, :3] = assist_force+load_force
        d.xfrc_applied[pelvis, 3:] = assist_torque
        mj.mj_forward(m, d)
        try:
            if d.warning.number.any() or not all(np.isfinite(v).all() for v in (d.qpos, d.qvel, d.act, d.qacc, d.actuator_force)):
                raise ValueError("nonfinite state or engine warning; trajectory stopped")
            ground, ground_moment, records, geometry, friction_error = measure_contacts(mj, m, d, floor, step)
            acc, hdot, com_velocity = momentum_rates(mj, m, d, scratch, pelvis, rules.kinematic_difference_step_s)
            external_force = assist_force+load_force
            external_moment = assist_torque+np.cross(d.xipos[pelvis]-d.subtree_com[pelvis], external_force)
            f_res = mass*acc-ground-mass*m.opt.gravity-external_force
            t_res = hdot-ground_moment-external_moment
            q = d.qpos[m.jnt_qposadr]
            violations = np.maximum(0, np.maximum(m.jnt_range[:, 0]-q, q-m.jnt_range[:, 1]))
            slide = m.jnt_limited.astype(bool) & (m.jnt_type == mj.mjtJoint.mjJNT_SLIDE)
            hinge = m.jnt_limited.astype(bool) & (m.jnt_type == mj.mjtJoint.mjJNT_HINGE)
            pen = max([0.0, *(-r["gap_m"] for r in records)])
            row = {"sample": step, "time_s": float(d.time), "floor_contact_count": sum(r["floor_contact"] for r in records),
                   "force_bearing_floor_contact_count": sum(r["floor_contact"] and r["normal_force_N"] > 1e-6 for r in records),
                   "weight_N": mass*9.81, "max_penetration_m": pen, "force_residual_N": float(np.linalg.norm(f_res)),
                   "moment_residual_Nm": float(np.linalg.norm(t_res)), "friction_violation_N": float(friction_error),
                   "hinge_limit_violation_rad": float(violations[hinge].max(initial=0)), "slide_limit_violation_m": float(violations[slide].max(initial=0)),
                   "support_area_m2": geometry["area_m2"], "com_projection_inside": int(geometry["com_projection_inside"]),
                   "cop_valid": int(geometry["cop_xy_m"] is not None),
                   "cop_x_m": geometry["cop_xy_m"][0] if geometry["cop_xy_m"] else None,
                   "cop_y_m": geometry["cop_xy_m"][1] if geometry["cop_xy_m"] else None,
                   "assist_power_W": float(assist_force @ velocity+assist_torque @ omega), "load_power_W": float(load_force @ velocity)}
            for prefix, vector in (("grf", ground), ("assist_force", assist_force), ("assist_torque", assist_torque),
                                   ("com", d.subtree_com[pelvis]), ("com_velocity", com_velocity), ("com_acceleration", acc),
                                   ("angular_momentum_rate", hdot), ("ground_moment_com", ground_moment),
                                   ("external_moment_com", external_moment), ("root", d.xpos[pelvis])):
                unit = "Nm" if "moment" in prefix or "torque" in prefix else "N" if prefix in ("grf", "assist_force") else "m_per_s2" if prefix == "com_acceleration" else "m_per_s" if prefix == "com_velocity" else "m"
                for axis, value in zip("xyz", vector, strict=True):
                    row[f"{prefix}_{axis}_{unit}"] = float(value)
            root_jac = np.zeros((3, m.nv))
            mj.mj_jacBody(m, d, root_jac, jrot, pelvis)
            row["root_speed_m_per_s"] = float(np.linalg.norm(root_jac @ d.qvel))
            contacts.extend(records)
            support.append(geometry)
            rows.append(row)
            mj.mj_getState(m, d, state, state_spec)
            states.append(state.copy())
            qpos.append(d.qpos.copy())
            qvel.append(d.qvel.copy())
            for key in vectors:
                vectors[key].append(getattr(d, key).copy())
            if step == 0:
                np.savez_compressed(output / "initial_state.npz", state=state, state_spec=int(state_spec))
            guards = [("force balance", row["force_residual_N"], rules.force_balance_tolerance_N),
                      ("moment balance", row["moment_residual_Nm"], rules.moment_balance_tolerance_Nm),
                      ("penetration", pen, rules.max_penetration_m), ("friction", friction_error, rules.friction_tolerance_N),
                      ("hinge soft limit", row["hinge_limit_violation_rad"], rules.max_hinge_limit_violation_rad),
                      ("slide soft limit", row["slide_limit_violation_m"], rules.max_slide_limit_violation_m)]
            for name, value, tolerance in guards:
                if value > tolerance:
                    raise ValueError(f"{name} check failed: {value:.9g} > {tolerance:.9g}; partial numeric files retained")
        except ValueError as exc:
            failure = str(exc)
            break
    if not rows:
        return error("failed", failure or "no finite samples")
    bearing_sides = {m.geom(r["geom1"] if r["geom0"] == floor else r["geom0"]).name[-1]
                     for r in contacts if r["floor_contact"] and r["normal_force_N"] > 1e-6}
    if bearing_sides != {"r", "l"}:
        failure = failure or "bilateral force-bearing floor support did not occur; contact candidates alone are insufficient"
    with (output / "series.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    times = np.array([r["time_s"] for r in rows])
    np.savez_compressed(output / "trajectory.npz", states=np.array(states), state_spec=int(state_spec), time_s=times,
                        qpos=np.array(qpos), qvel=np.array(qvel), **{key: np.array(value) for key, value in vectors.items()})
    dump(output / "poses.json", {"model_id": MODEL_ID, "method": "dynamic_forward", "time_s": times.tolist(),
         "qpos": np.array(qpos).tolist(), "joint_order": [m.joint(i).name for i in range(m.njnt)]})
    dump(output / "support.json", {"samples": support, "definition": "Convex hull of XY projections of current foot-floor contact points with normal force >1e-6 N; not full anatomical sole area or balance certification.",
         "cop_definition": "Equivalent ground-wrench CoP on z=0: x=-M_origin_y/Fz, y=M_origin_x/Fz if Fz>1e-6 N. Not a ZMP/clinical metric; auxiliary contact moments included.",
         "degenerate_area_threshold_m2": 1e-10})
    contact_files = []
    for first in range(0, len(contacts), 500):
        name = f"contacts_{first//500:03d}.json"
        dump(output / name, contacts[first:first+500])
        contact_files.append(name)
    dump(output / "contacts.json", {"files": contact_files, "records": len(contacts), "geometries": mapping["collision_geometries"],
         "wrench_convention": "Local force/torque acts on the second contact geometry: contact.geom[1], JSON key geom1. World = frame_rows.T @ local. Ground reaction on the body reverses sign when floor is contact.geom[1].",
         "units": {"position_m": "m", "gap_m": "m", "local_force_N": "N", "local_torque_Nm": "N*m"}})
    metrics = [{"name": "model_mass", "value": mass, "unit": "kg"}, {"name": "model_weight", "value": mass*9.81, "unit": "N"},
               {"name": "elapsed_time", "value": float(times[-1]), "unit": "s"},
               {"name": "final_ground_reaction_z", "value": rows[-1]["grf_z_N"], "unit": "N"},
               {"name": "final_assist_force_z", "value": rows[-1]["assist_force_z_N"], "unit": "N"},
               {"name": "final_com_height", "value": rows[-1]["com_z_m"], "unit": "m"},
               {"name": "com_height_change", "value": rows[-1]["com_z_m"]-rows[0]["com_z_m"], "unit": "m"},
               {"name": "ground_vertical_impulse", "value": float(np.trapezoid([r["grf_z_N"] for r in rows], times)), "unit": "N*s"},
               {"name": "external_assist_work", "value": float(np.trapezoid([r["assist_power_W"] for r in rows], times)), "unit": "J", "definition": "Trapezoid integral of world force dot pelvis COM velocity + world torque dot angular velocity; no total-energy claim."},
               {"name": "external_load_work", "value": float(np.trapezoid([r["load_power_W"] for r in rows], times)), "unit": "J"}]
    for key, unit in (("force_residual_N", "N"), ("moment_residual_Nm", "N*m"), ("max_penetration_m", "m"),
                      ("hinge_limit_violation_rad", "rad"), ("slide_limit_violation_m", "m"), ("friction_violation_N", "N")):
        metrics.append({"name": key if key.startswith("max_") else "max_"+key, "value": max(r[key] for r in rows), "unit": unit})
    dump(output / "summary.json", {"status": "partial" if failure else "computed", "error": failure, "metrics": metrics, "rows": rows})
    if failure:
        return error("failed", failure)
    if abs(times[-1]-p.duration_s) > 1e-12:
        return error("failed", "duration mismatch")
    render_info = {"status": "not_requested", "render_backend": "none"}
    if p.render:
        try:
            from .contact_visualization import render_contact
            render_info = render_contact(mj, m, output, recipe)
        except Exception as exc:
            render_info = {"status": "failed", "render_backend": "none", "message": str(exc)[:1000]}
    units = {}
    for name in rows[0]:
        units[name] = "m/s2" if name.endswith("_m_per_s2") else "m/s" if name.endswith("_m_per_s") else "N*m" if name.endswith("_Nm") else "m2" if name.endswith("_m2") else "m" if name.endswith("_m") else "rad" if name.endswith("_rad") else "s" if name == "time_s" else "N" if name.endswith("_N") else "W" if name.endswith("_W") else "1"
    return {"status": "computed", "metrics": metrics, "render": render_info, "counts": {"nq": m.nq, "nv": m.nv, "actuators": m.nu, "tendons": m.ntendon, "equality_constraints": m.neq},
            "checks": [{"name": name, "status": "pass"} for name in ("finite_state", "zero_engine_warnings", "native_contact_map", "initial_bilateral_contact_candidates", "bilateral_force_bearing_support_observed",
                       "world_frame_force_balance", "com_angular_momentum_balance", "friction_pyramid", "geometric_penetration_bound", "separate_joint_limit_units", "fixed_duration")],
            "integration_steps": p.steps, "simulation_time_s": float(times[-1]), "integrator": mj.mjtIntegrator(int(m.opt.integrator)).name,
            "model_derivation": recipe, "controller": recipe["controller"], "initial_conditions": initial, "timestep_s": m.opt.timestep,
            "limitations": ["Short model contact transient with native skin capsules and positive contact margins; not measured plantar pressure or complete tissue collision.",
                            "Initial pose is geometrically adjusted and local knee equalities enforced, not initialized at equilibrium.",
                            "Assisted run uses explicit external pelvis forces/torques; neither run certifies unassisted balance or human movement safety.",
                            "Support hull is from current point contacts; COM/CoP inclusion alone does not prove dynamic stability.",
                            "Newton/momentum checks and refinement establish numerical consistency, without experimental contact-force or clinical validation."],
            "time_series": {"artifact_id": "series.csv", "axis": "time_s", "units": units,
                            "definition": "World z upward. M*a_COM = GRF + M*g + external pelvis force. Hdot_COM = ground moment about COM + external pelvis moment about COM. Kinematic matrix derivatives use declared central differences; support work uses recorded body velocity."},
            "contact_outputs": {"metadata_artifact": "contacts.json", "support_artifact": "support.json", "model_map_artifact": "contact_map.json",
                                "trajectory_metadata_artifact": "trajectory_metadata.json",
                                "wrench_units": {"force": "N", "torque": "N*m"}, "support_area_unit": "m2"}}
