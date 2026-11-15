"""Bounded full-primary-model push-up dynamics with measured muscle recruitment."""

import csv
from pathlib import Path

import numpy as np

from ..registry import ForwardValidation, PushupParameters, home
from .contact import dump, measure_contacts, momentum_rates

PADS = ("palm_r", "palm_l", "toe_r", "toe_l")
ARM = ("elv_angle", "shoulder_elv", "shoulder_rot", "elbow_flexion", "pro_sup", "deviation", "flexion")
CITATIONS = [
    {"title": "Youdas et al. 2010, conventional push-up EMG", "url": "https://pubmed.ncbi.nlm.nih.gov/20664364/"},
    {"title": "Marcolin et al. 2015, shoulder, trunk and arm EMG in push-up variants",
     "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4732391/"},
]
LIMITATIONS = [
    "Synthetic engineering reference and bounded recruitment feedback; not measured human motion or a validated neural controller.",
    "Added massless spherical palm/toe contact pads and plane; these are mechanical proxies, not inferred anatomical tissue or flat-palm pressure.",
    "Source self-collision retained; source visual bones do not provide complete tissue collision coverage.",
    "Added internal viscous damping floor 10 N*m*s/rad (hinges), 10 N*s/m (slides); this changes passive mechanics and dissipates energy.",
    "Source shoulder/scapular joint equalities prescribe scapulohumeral coupling; scapular motion is not independently controlled.",
    "All 700 native muscle dynamics/transmissions retained, but force parameters and recruitment are unvalidated for push-ups.",
    "Model activation is dimensionless dynamical state, not surface EMG, percent MVIC, clinical strength or injury risk.",
    "Native muscle-tendon paths are not muscle volumes; no external atlas registration or subject calibration.",
]


def pushup_model(timestep_s=0.001, friction=1.3, muscle_strength_scale=1.0, hand_support="legacy_point", support_boundary="frictional",
                 knuckle_technique="legacy_flared", palm_technique="legacy_reach"):
    import mujoco as mj

    spec = mj.MjSpec.from_file(str(home() / "models/ms_human_700/MS-Human-700.xml"))
    if hand_support != "legacy_point":
        from .hands import configure_hands
        spec, _ = configure_hands(spec, hand_support)
    if palm_technique == "chest_full":
        # The physical shaft-angle gate is separate from this literature-informed coordinate box.
        for side in "rl":
            spec.joint("flexion_" + side).range[0] = -.930016
    spec.option.timestep = timestep_s
    spec.option.integrator = mj.mjtIntegrator.mjINT_IMPLICITFAST
    spec.option.tolerance, spec.option.iterations = 1e-10, 100
    spec.worldbody.add_geom(name="floor", type=mj.mjtGeom.mjGEOM_PLANE, size=[3, 3, .1],
                            contype=4, conaffinity=2, friction=[friction, .005, .0001], solref=[.01, 1],
                            rgba=[.15, .18, .23, 1])
    for side in "rl":
        for body, kind, pos, radius in (("hand", "palm", [0, -.08, 0], .025),
                                        ("toes", "toe", [.04, 0, 0], .015)):
            if body == "hand" and hand_support != "legacy_point":
                continue
            spec.body(body + "_" + side).add_geom(
                name=kind + "_" + side, type=mj.mjtGeom.mjGEOM_SPHERE, pos=pos, size=[radius, 0, 0],
                mass=0, contype=2, conaffinity=4, friction=[friction, .005, .0001],
                solref=[.01, 1], rgba=[.1, .6, .7, .6])
    model = spec.compile()
    for i in range(model.ngeom):
        if model.geom(i).name.startswith("palm_"):
            model.geom_friction[i, 0] = friction
    if (model.nq, model.nv, model.nu, model.neq) != (85, 85, 700, 42):
        raise ValueError("pushup requires the pinned full primary model with 700 muscles and 42 equalities")
    if not np.all(model.actuator_dyntype == mj.mjtDyn.mjDYN_MUSCLE):
        raise ValueError("non-muscle actuator in primary model")
    if support_boundary == "fixed_points":
        from .supports import add_fixed_supports
        initial = mj.MjData(model)
        mj.mj_resetDataKeyframe(model, initial, 0)
        poses, _ = reference_poses(mj, model, initial, hand_support, initial_only=True)
        add_fixed_supports(mj, spec, model, initial, poses[0])
        model = spec.compile()
        model.key_qpos[0, :85] = poses[0]
        if hand_support in ("palms", "knuckles"):
            from .supports import fixed_reference_poses
            adjusted, _ = fixed_reference_poses(mj, model, mj.MjData(model),
                yaw=.3 if hand_support == "palms" else -.9, forward_shift=.09 if hand_support == "palms" else 0,
                peak_elbow=1.5 if hand_support == "palms" else 1.55, initial_elbow=.2 if hand_support == "palms" else .1, initial_only=True)
            check = mj.MjData(model)
            check.qpos[:] = adjusted[0]
            mj.mj_kinematics(model, check)
            for name in PADS:
                point = check.site_xpos[model.site("material_" + name).id].copy()
                point[2] = float(model.geom_size[model.geom(name).id, 0]) if name.startswith("toe_") else 0
                spec.body("support_guide_" + name).pos = point
            model = spec.compile()
            model.key_qpos[0] = adjusted[0]
            if hand_support == "palms" and palm_technique in ("chest_level", "chest_full"):
                from .supports import chest_palm_reference, full_palm_reference
                adjusted, _ = (full_palm_reference(mj, model, initial_only=True) if palm_technique == "chest_full"
                               else chest_palm_reference(mj, model))
                check.qpos[:] = adjusted[0]
                mj.mj_kinematics(model, check)
                for name in PADS:
                    point = check.site_xpos[model.site("material_" + name).id].copy()
                    point[2] = float(model.geom_size[model.geom(name).id, 0]) if name.startswith("toe_") else 0
                    spec.body("support_guide_" + name).pos = point
                model = spec.compile()
                model.key_qpos[0] = adjusted[0]
            if hand_support == "knuckles":
                adjusted, _ = fixed_reference_poses(mj, model, mj.MjData(model), initial_elbow=.03, peak_elbow=1.55, initial_only=True)
                model.key_qpos[0] = adjusted[0]
                if knuckle_technique == "neutral_tucked":
                    from .supports import tucked_knuckle_start
                    pose = tucked_knuckle_start(mj, model)
                    check.qpos[:] = pose
                    mj.mj_kinematics(model, check)
                    for name in PADS:
                        point = check.site_xpos[model.site("material_" + name).id].copy()
                        point[2] = float(model.geom_size[model.geom(name).id, 0]) if name.startswith("toe_") else 0
                        spec.body("support_guide_" + name).pos = point
                    model = spec.compile()
                    model.key_qpos[0] = pose
        model.key_qpos[0, 1] -= .00002
        model.key_qpos[0, 85:] -= .00002
        for g in range(model.ngeom):
            if model.geom(g).name == "floor" or model.geom(g).name.startswith(("palm_", "toe_")):
                model.geom_friction[g, 0] = friction
                model.geom_solref[g] = [.004, 1]
                model.geom_solimp[g, :2] = [.95, .99]
                model.geom_margin[g] = 0
        model.opt.jacobian = mj.mjtJacobian.mjJAC_DENSE
        model.eq_solref[model.eq_type == mj.mjtEq.mjEQ_JOINT] = [.004, 1]
        model.eq_solimp[model.eq_type == mj.mjtEq.mjEQ_JOINT, :2] = [.9999, .9999]
    model.dof_damping[6:85] = np.maximum(model.dof_damping[6:85], 10)
    # Scale both active gain and passive muscle force; preserve the source curve shapes.
    model.actuator_gainprm[:, 2] *= muscle_strength_scale
    model.actuator_biasprm[:, 2] *= muscle_strength_scale
    data = mj.MjData(model)
    mj.mj_resetDataKeyframe(model, data, 0)
    return mj, model, data


def couple(model, qpos):
    for eq in range(model.neq):
        if model.eq_type[eq] != 2:  # mjEQ_JOINT; positional ground constraints are not source coordinate couplings.
            continue
        child, parent = int(model.eq_obj1id[eq]), int(model.eq_obj2id[eq])
        qpos[child] = model.qpos0[child] + np.polynomial.polynomial.polyval(
            qpos[parent] - model.qpos0[parent], model.eq_data[eq, :5])


def reference_poses(mj, model, data, hand_support="legacy_point", initial_only=False, knuckle_technique="legacy_flared",
                    palm_technique="legacy_reach"):
    """IK defines targets only; the integration loop never assigns a target to qpos."""
    if mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE, "material_toe_r") >= 0:
        if palm_technique == "chest_full":
            from .supports import full_palm_reference
            return full_palm_reference(mj, model, initial_only)
        if palm_technique == "chest_level":
            from .supports import chest_palm_reference
            poses, info = chest_palm_reference(mj, model)
            return poses[:1] if initial_only else poses, info
        from .supports import fixed_reference_poses
        tucked = knuckle_technique == "neutral_tucked"
        return fixed_reference_poses(mj, model, data, peak_elbow=1.9 if tucked else 1.525 if hand_support == "palms" else 1.625,
                                     initial_elbow=.2 if hand_support == "palms" or tucked else .03,
                                     initial_only=initial_only, tucked=tucked)
    def kinematics(qpos):
        data.qpos[:] = qpos
        couple(model, data.qpos)
        mj.mj_kinematics(model, data)
        mj.mj_comPos(model, data)
        return data.qpos.copy()

    def aligned(qpos):
        qpos = kinematics(qpos)
        toe = data.geom_xpos[model.geom("toe_r").id].copy()
        qpos[:3] += [toe[1] + .085, .015 - toe[2], -toe[0]]
        return kinematics(qpos)

    qpos = data.qpos.copy()
    qpos[3] = -1.15
    qpos = aligned(qpos)
    hand_x = float(data.xpos[model.body("humerus_r").id, 0] + (.5 if hand_support == "palms" else .02))
    height = .025 if hand_support == "legacy_point" else .009
    targets = np.array([[hand_x, -.24, height], [hand_x, .24, height]])
    hand_pads = {s: [i for i in range(model.ngeom) if model.geom(i).name.startswith("palm_" + s)] for s in "rl"}
    indices = [3] + [model.joint(n + "_" + s).id for s in "rl" for n in ARM]
    low, high = model.jnt_range[indices, 0] + 1e-4, model.jnt_range[indices, 1] - 1e-4

    def residual(q, elbow):
        q = aligned(q)
        values = []
        for side, target in zip("rl", targets, strict=True):
            values.extend((np.mean(data.geom_xpos[hand_pads[side]], axis=0) - target) * 5)
            values.append((q[model.joint("elbow_flexion_" + side).id] - elbow) * .6)
            if hand_support == "legacy_point":
                values.extend(q[model.joint(n + "_" + side).id] * .05 for n in ARM[-3:])
            else:
                local = [0, 0, -1 if side == "r" else 1] if hand_support == "palms" else [0, -1, 0]
                normal = data.xmat[model.body("hand_" + side).id].reshape(3, 3) @ local
                values.extend((normal - [0, 0, -1]) * .7)
                values.append(q[model.joint("deviation_" + side).id] * .02)
                if hand_support == "knuckles":
                    values.append(q[model.joint("flexion_" + side).id] * .02)
        return np.array(values)

    for side in "rl":
        for name, value in zip(ARM[:4], (0, 1.3, .3, .2), strict=True):
            qpos[model.joint(name + "_" + side).id] = value
    poses, errors = [], []
    for elbow in np.linspace(.2, 1.8, 1 if initial_only else 17):
        for _ in range(200 if hand_support != "legacy_point" else 80):
            error = residual(qpos, elbow)
            if np.linalg.norm(error) < 1e-5:
                break
            jacobian = np.empty((len(error), len(indices)))
            for col, joint in enumerate(indices):
                probe = qpos.copy()
                probe[joint] += 1e-5
                jacobian[:, col] = (residual(probe, elbow) - error) / 1e-5
            delta = -jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + .0001 * np.eye(len(error)), error)
            qpos[indices] = np.clip(qpos[indices] + np.clip(delta, -.15, .15), low, high)
        errors.append(float(np.linalg.norm(residual(qpos, elbow))))
        if errors[-1] > (0.01 if hand_support == "knuckles" else 1e-4):
            raise ValueError("pushup reference IK did not converge")
        poses.append(aligned(qpos))
    return np.array(poses), {"method": "bounded damped least-squares engineering IK", "max_residual": max(errors),
                             "hand_targets_m": targets.tolist(), "reference_only": True}



def target_pose(poses, time_s, cycle_s=2.0):
    phase = np.sin(np.pi * np.clip((time_s - .2) / cycle_s, 0, 1)) ** 2
    coordinate = phase * (len(poses) - 1)
    index = min(int(coordinate), len(poses) - 2)
    return poses[index] + (coordinate - index) * (poses[index + 1] - poses[index])


def transmission(model, data):
    matrix = np.zeros((model.nu, model.nv))
    for act in range(model.nu):
        start, count = int(data.moment_rowadr[act]), int(data.moment_rownnz[act])
        matrix[act, data.moment_colind[start:start + count]] = data.actuator_moment[start:start + count]
    return matrix


def coordinate_tangent(model, data, active):
    tangent = np.zeros((model.nv, len(active)))
    tangent[active, np.arange(len(active))] = 1
    for eq in range(model.neq):
        if model.eq_type[eq] != 2:
            continue
        child, parent = int(model.eq_obj1id[eq]), int(model.eq_obj2id[eq])
        derivative = np.polynomial.polynomial.polyval(
            data.qpos[parent] - model.qpos0[parent], np.arange(1, 5) * model.eq_data[eq, 1:5])
        tangent[child] = tangent[parent] * derivative
    return tangent


def recruit(mj, model, data, active, target):
    """Box-constrained force allocation; actual activation still evolves through mj_step."""
    tangent = coordinate_tangent(model, data, active)
    jacobian = transmission(model, data) @ tangent
    saved = data.act.copy()
    data.act[:] = 0
    mj.mj_fwdActuation(model, data)
    passive = data.actuator_force.copy()
    data.act[:] = 1
    mj.mj_fwdActuation(model, data)
    gain = data.actuator_force - passive
    data.act[:] = saved
    mj.mj_fwdActuation(model, data)
    matrix = jacobian.T * gain
    rhs = target - jacobian.T @ passive
    scale = np.maximum(np.linalg.norm(matrix, axis=1), 10)
    matrix, rhs = matrix / scale[:, None], rhs / scale
    rate = 1 / (np.linalg.norm(matrix, 2) ** 2 + 1e-5)
    excitation = data.ctrl.copy()
    extrapolated, alpha = excitation.copy(), 1.0
    for _ in range(300):
        updated = np.clip(extrapolated - rate * (matrix.T @ (matrix @ extrapolated - rhs) + 1e-5 * extrapolated), 0, 1)
        next_alpha = (1 + np.sqrt(1 + 4 * alpha * alpha)) / 2
        extrapolated = updated + (alpha - 1) / next_alpha * (updated - excitation)
        excitation, alpha = updated, next_alpha
    data.ctrl[:] = excitation
    return float(np.linalg.norm(matrix @ excitation - rhs))


def anatomical_group(name):
    for prefixes, group in (
        (("PECM",), "pectoralis_major"), (("TRI",), "triceps_brachii"),
        (("SerrAnt",), "serratus_anterior"), (("DELT",), "deltoid"),
        (("rect_abd",), "rectus_abdominis"), (("EO_",), "external_oblique"),
        (("IO",), "internal_oblique"), (("trap_",), "trapezius"),
        (("TR1_", "TR2_", "TR3_", "TR4_", "TR5_"), "abdominal_transverse_paths"),
        (("FCR", "FCU", "PL_", "FDS", "FDP", "FPL"), "forearm_flexors"),
        (("ECR", "ECU", "EDC", "EDM", "EIP", "EPL", "EPB"), "forearm_extensors"),
        (("BIClong", "BICshort"), "biceps_brachii"),
        (("IL_", "LTp", "MF_", "QL_", "multifidus"), "spinal_stabilizer_paths"),
    ):
        if name.startswith(prefixes):
            return group
    return "unmapped_source_identifier"


def simulate_pushup(params: dict, output: Path, validation: dict):
    p = PushupParameters.model_validate(params)
    ForwardValidation.model_validate(validation)
    mj, model, data = pushup_model(p.timestep_s, p.friction, p.muscle_strength_scale, p.hand_support, p.support_boundary, p.knuckle_technique, p.palm_technique)
    poses, ik = reference_poses(mj, model, data, p.hand_support, knuckle_technique=p.knuckle_technique, palm_technique=p.palm_technique)
    data.qpos[:], data.qvel[:], data.act[:], data.ctrl[:] = poses[0], 0, 0, 0
    mj.mj_forward(model, data)
    initial_qpos = data.qpos.copy()
    hand_orientation = {s: data.xquat[model.body("hand_" + s).id].copy() for s in "rl"}
    pad_ids = [i for n in PADS for i in range(model.ngeom) if model.geom(i).name == n or model.geom(i).name.startswith(n + "_")]
    pad_names = [model.geom(i).name for i in pad_ids]
    pad_groups = [next(i for i, n in enumerate(PADS) if model.geom(g).name == n or model.geom(g).name.startswith(n + "_")) for g in pad_ids]
    initial_pads = data.geom_xpos[pad_ids].copy()
    dependent = set(map(int, model.eq_obj1id[model.eq_type == mj.mjtEq.mjEQ_JOINT]))
    active = np.array([j for j in range(6, 85) if j not in dependent])
    gains = np.full(model.nq, 600.0)
    if p.hand_support != "legacy_point":
        gains[6:45] = 3500
        gains[45:85] = 2000
    if p.support_boundary == "fixed_points":
        gains[[15, 16, 17, 30, 31, 32]] = 0
    pelvis, floor = model.body("pelvis").id, model.geom("floor").id
    scratch = mj.MjData(model)
    mass = float(model.body_subtreemass[pelvis])
    state_spec = mj.mjtState.mjSTATE_INTEGRATION
    state = np.empty(mj.mj_stateSize(model, state_spec))
    cycle_s = 4.0 if p.support_boundary == "fixed_points" else 2.0
    duration_s = cycle_s + .4
    sample_interval = .04 if p.support_boundary == "fixed_points" else .02
    steps = round(duration_s / p.timestep_s)
    save_every, control_every = round(sample_interval / p.timestep_s), round(.01 / p.timestep_s)
    rows, states, qposes, supports, contacts, muscle_samples = [], [], [], [], [], []
    wrist_samples = []
    force_integral, activation_integral, work = np.zeros(model.nu), np.zeros(model.nu), np.zeros(model.nu)
    external_work = 0.0
    contact_counts = np.zeros(4)
    max_penetration = max_limit_hinge = max_limit_slide = max_slip = 0.0
    max_external = max_balance = max_moment_balance = max_transmission_error = max_friction_error = 0.0
    max_plank_deviation = max_wrist_extension = 0.0
    max_anchor_speed = support_work = 0.0
    anchor_displacements = {}
    pad_displacements = {}
    residual = 0.0
    from ..anatomy import path_regions
    regions = path_regions(model)
    region_indices = {region: [i for i in range(model.nu) if region in regions[model.actuator(i).name]]
                      for region in ("arm_muscles", "lumbar_muscles", "abdominal_muscles", "hand_tendons")}
    for step in range(steps + 1):
        if step:
            mj.mj_step(model, data)
        mj.mj_forward(model, data)
        reference = target_pose(poses, float(data.time), cycle_s)
        desired = np.clip(gains[active] * (reference[active] - data.qpos[active]), -200, 200)
        if p.support_boundary == "fixed_points":
            from .supports import fixed_support_command
            desired = fixed_support_command(mj, model, data, poses, active, hand_orientation)
        elif p.hand_support == "palms":
            tangent = coordinate_tangent(model, data, active)
            for side in "rl":
                body = model.body("hand_" + side).id
                normal = data.xmat[body].reshape(3, 3) @ [0, 0, -1 if side == "r" else 1]
                linear, angular = np.zeros((3, model.nv)), np.zeros((3, model.nv))
                mj.mj_jacBody(model, data, linear, angular, body)
                correction = (angular @ tangent).T @ (10000 * np.cross(normal, [0, 0, -1]))
                for name in ("flexion", "deviation"):
                    index = int(np.flatnonzero(active == model.joint(name + "_" + side).id)[0])
                    desired[index] = np.clip(desired[index] + correction[index], -200, 200)
        data.qfrc_applied[:] = 0
        if p.control == "external":
            data.qfrc_applied[active] = desired
        else:
            if step % control_every == 0:
                residual = recruit(mj, model, data, active, desired)
            if p.control == "assisted_muscle":
                muscle_torque = coordinate_tangent(model, data, active).T @ data.qfrc_actuator
                data.qfrc_applied[active] = np.clip(desired - muscle_torque, -200, 200)
        mj.mj_forward(model, data)
        if data.warning.number.any() or not all(np.isfinite(a).all() for a in
                (data.qpos, data.qvel, data.qacc, data.act, data.actuator_force)):
            raise ValueError("nonfinite state or engine warning in pushup")
        if np.min(data.act) < -1e-10 or np.max(data.act) > 1 + 1e-10:
            raise ValueError("activation outside [0,1]")
        max_external = max(max_external, float(np.max(np.abs(data.qfrc_applied))))
        max_plank_deviation = max(max_plank_deviation, float(np.max(np.abs(data.qpos[[6, 12, 21, 27, 36, 39]]))))
        if p.palm_technique == "chest_full":
            from .hands import wrist_shaft_extension
            max_wrist_extension = max(max_wrist_extension, *(wrist_shaft_extension(model, data, s) for s in "rl"))
        if np.any(data.qfrc_applied[:6]) or np.any(data.xfrc_applied):
            raise ValueError("external root force or body wrench prohibited")
        violation = np.maximum(model.jnt_range[:, 0] - data.qpos, data.qpos - model.jnt_range[:, 1])
        max_limit_hinge = max(max_limit_hinge, float(np.max(violation[:85][model.jnt_type[:85] == mj.mjtJoint.mjJNT_HINGE])))
        max_limit_slide = max(max_limit_slide, float(np.max(violation[:85][model.jnt_type[:85] == mj.mjtJoint.mjJNT_SLIDE])))
        bearing = np.zeros(4)
        support_forces = np.zeros((4, 3))
        if p.support_boundary == "fixed_points":
            from .supports import fixed_reactions
            for reaction in fixed_reactions(mj, model, data):
                group = next(i for i, name in enumerate(PADS) if reaction["geom"] == name or reaction["geom"].startswith(name + "_"))
                bearing[group] += reaction["normal_force_N"]
                support_forces[group] += reaction["force_world_N"]
                name = reaction["geom"]
                anchor_displacements[name] = max(anchor_displacements.get(name, 0), reaction["displacement_m"])
                max_slip = max(max_slip, reaction["displacement_m"])
                max_anchor_speed = max(max_anchor_speed, reaction["speed_m_per_s"])
                if step < steps:
                    support_work += reaction["power_W"] * p.timestep_s
        for contact_id in range(data.ncon):
            contact = data.contact[contact_id]
            max_penetration = max(max_penetration, -float(contact.dist))
            if floor in contact.geom:
                other = int(contact.geom[1] if contact.geom[0] == floor else contact.geom[0])
                if other not in pad_ids:
                    raise ValueError("unexpected non-pad floor contact")
                local = np.zeros(6)
                mj.mj_contactForce(model, data, contact_id, local)
                bearing[pad_groups[pad_ids.index(other)]] += local[0]
                if p.support_boundary == "fixed_points":
                    sign = 1 if contact.geom[0] == floor else -1
                    support_forces[pad_groups[pad_ids.index(other)]] += sign * contact.frame.reshape(3, 3).T @ local[:3]
        if p.support_boundary == "fixed_points":
            max_friction_error = max(max_friction_error, float(np.max(
                np.linalg.norm(support_forces[:, :2], axis=1) - p.friction * support_forces[:, 2])),
                -float(np.min(support_forces[:, 2])))
        if step >= round(.2 / p.timestep_s):
            contact_counts += bearing > 1
        patch_drift = np.linalg.norm(data.geom_xpos[pad_ids, :2] - initial_pads[:, :2], axis=1)
        max_slip = max(max_slip, float(np.max(patch_drift)))
        for name, displacement in zip(pad_names, patch_drift, strict=True):
            pad_displacements[name] = max(pad_displacements.get(name, 0), float(displacement))
        if step < steps:
            force_integral += np.abs(data.actuator_force) * p.timestep_s
            activation_integral += data.act * p.timestep_s
            work += data.actuator_force * data.actuator_velocity * p.timestep_s
            external_work += float(data.qfrc_applied @ data.qvel) * p.timestep_s
        if step % save_every:
            continue
        sample = len(rows)
        if p.support_boundary == "fixed_points":
            from .supports import measure_fixed_supports
            ground, moment, records, support, friction_error = measure_fixed_supports(mj, model, data, sample, p.friction)
        else:
            ground, moment, records, support, friction_error = measure_contacts(
                mj, model, data, floor, sample, allowed_prefixes=("palm_", "toe_"))
        acceleration, hdot, _ = momentum_rates(mj, model, data, scratch, pelvis, 1e-6)
        balance = float(np.linalg.norm(mass * acceleration - ground - mass * model.opt.gravity))
        moment_error = float(np.linalg.norm(hdot - moment))
        matrix = transmission(model, data)
        transmission_error = float(np.max(np.abs(matrix.T @ data.actuator_force - data.qfrc_actuator)))
        max_balance, max_moment_balance = max(max_balance, balance), max(max_moment_balance, moment_error)
        max_transmission_error, max_friction_error = max(max_transmission_error, transmission_error), max(max_friction_error, friction_error)
        row = {"sample": sample, "time_s": float(data.time), "angle_rad": float(data.qpos[59]),
               "left_elbow_rad": float(data.qpos[79]), "target_angle_rad": float(reference[59]),
               "pelvis_height_m": float(data.xpos[pelvis, 2]),
               "chest_height_m": float(np.mean(data.xpos[[model.body("humerus_" + s).id for s in "rl"], 2])),
               "trunk_pitch_rad": float(data.qpos[3]), "hip_flexion_r_rad": float(data.qpos[6]),
               "knee_r_rad": float(data.qpos[12]), "weight_N": mass * 9.81,
               "grf_x_N": float(ground[0]), "grf_y_N": float(ground[1]), "grf_z_N": float(ground[2]),
               "force_balance_error_N": balance, "moment_balance_error_Nm": moment_error,
               "recruitment_scaled_residual": residual, "max_activation": float(max(data.act)),
               "external_torque_max_Nm": float(np.max(np.abs(data.qfrc_applied))),
               "applied_torque_Nm": float(data.qfrc_applied[59]),
               "left_elbow_external_torque_Nm": float(data.qfrc_applied[79]),
               "external_power_W": float(data.qfrc_applied @ data.qvel)}
        for group in ("pectoralis_major", "triceps_brachii", "serratus_anterior", "rectus_abdominis", "deltoid"):
            ids = [i for i in range(model.nu) if anatomical_group(model.actuator(i).name) == group]
            row[group + "_activation"] = float(np.mean(data.act[ids]))
        row.update({region + "_activation": float(np.mean(data.act[ids])) for region, ids in region_indices.items()})
        row.update({n + "_normal_N": float(f) for n, f in zip(PADS, bearing, strict=True)})
        row["support_patch_displacement_m"] = float(np.max(patch_drift))
        if p.hand_support != "legacy_point":
            from .hands import measure_wrists
            wrist_values, wrist_details = measure_wrists(mj, model, data, p.hand_support)
            row.update(wrist_values)
            wrist_samples.append({"sample": sample, "hands": wrist_details})
        if p.hand_support == "knuckles":
            from .hands import measure_knuckle_technique
            row.update(measure_knuckle_technique(model, data))
        elif p.hand_support == "palms":
            from .hands import measure_palm_technique
            row.update(measure_palm_technique(model, data))
        rows.append(row)
        mj.mj_getState(model, data, state, state_spec)
        states.append(state.copy())
        qposes.append(data.qpos.copy())
        supports.append(support)
        contacts.extend(records)
        muscle_samples.append({"excitation": data.ctrl.copy(), "activation": data.act.copy(),
            "force_N": data.actuator_force.copy(), "length_m": data.actuator_length.copy(),
            "velocity_m_per_s": data.actuator_velocity.copy(),
            "power_W": (data.actuator_force * data.actuator_velocity).copy(),
            "moment_values": data.actuator_moment.copy(), "moment_columns": data.moment_colind.copy(),
            "moment_rowadr": data.moment_rowadr.copy(), "moment_rownnz": data.moment_rownnz.copy()})
    duration = float(data.time)
    if abs(duration - duration_s) > 1e-10:
        raise ValueError("pushup clock differs from requested integration")
    times = np.array([r["time_s"] for r in rows])
    np.savez_compressed(output / "trajectory.npz", states=states, state_spec=int(state_spec), time_s=times, qpos=qposes)
    np.savez_compressed(output / "reference.npz", qpos=poses)
    muscle_files = []
    for start in range(0, len(rows), 20):
        name = f"muscles_{start // 20:03d}.npz"
        np.savez_compressed(output / name, time_s=times[start:start + 20],
                            **{k: np.array([s[k] for s in muscle_samples[start:start + 20]]) for k in muscle_samples[0]})
        muscle_files.append(name)
    dump(output / "support.json", {"samples": supports})
    contact_files = []
    for start in range(0, len(contacts), 150):
        name = f"contacts_{start // 150:03d}.json"
        dump(output / name, {"contacts": contacts[start:start + 150]})
        contact_files.append(name)
    dump(output / "contacts.json", {"chunks": contact_files, "force_convention": "frame rows; local wrench on geom1; world=frame.T@local"})
    recipe = {"version": "1.0.0", "builder": "human_models_mcp.adapters.pushup.pushup_model",
              "source_variant": "primary", "timestep_s": p.timestep_s, "friction": p.friction,
              "muscle_strength_scale": p.muscle_strength_scale, "added_floor_and_pads": list(PADS),
              "added_root_support": False, "added_equalities": model.neq - 42, "passive_damping_floor": 10,
              "pad_floor_solref": [.004, 1] if p.support_boundary == "fixed_points" else [.01, 1], "solver_tolerance": 1e-10, "solver_iterations": 100,
              "integrator": "implicitfast", "floor_collision_masks": [4, 2], "pad_collision_masks": [2, 4],
              "parameters": p.model_dump(), "hand_support": p.hand_support, "support_boundary": p.support_boundary,
              "cycle_duration_s": cycle_s, "contact_preload_m": .00002 if p.support_boundary == "fixed_points" else 0, "ik": ik}
    if p.support_boundary == "fixed_points":
        recipe["fixed_supports"] = [{"geom": name, "body": model.body(model.site_bodyid[model.site("material_" + name).id]).name,
            "local_point_m": model.site_pos[model.site("material_" + name).id].tolist(),
            "world_anchor_m": model.body_pos[model.body("support_guide_" + name).id].tolist()} for name in PADS]
        recipe["fixed_support_solref"] = [.001, 1]
        recipe["fixed_support_solimp"] = [.9999, .9999, .001, .5, 2]
        recipe["support_guides"] = {"count": 4, "mass_each_kg": .0001, "vertical_damping_Ns_per_m": .01,
            "vertical_motion": "free; normal support remains unilateral native floor contact", "unactuated": True,
            "friction_check": "native contact cones plus aggregate Coulomb bound for each hand/foot; no pressure-map claim"}
    if p.hand_support != "legacy_point":
        from .hands import configure_hands
        _, recipe["hands"] = configure_hands(mj.MjSpec.from_file(str(home() / "models/ms_human_700/MS-Human-700.xml")), p.hand_support)
    if p.palm_technique == "chest_full":
        raw_reference = Path(__file__).with_name("palms_full_reference_v1.json").read_bytes()
        (output / "palm_reference_input.json").write_bytes(raw_reference)
        recipe["wrist_range_derivation"] = {
            "status": "literature-informed engineering envelope; not subject calibrated",
            "changed_limits_rad": {"flexion_r": [-.930016, .6], "flexion_l": [-.930016, .6]},
            "native_limits_rad": [-.6, .6], "other_joint_ranges_and_muscle_parameters": "unchanged",
            "shaft_extension_cap_rad": float(np.pi / 2), "numerical_tolerance_rad": .01,
            "measurement": "forearm shaft between native elbow/wrist anchors in native hand longitudinal/dorsal plane; geometric proxy, not clinical calibration",
            "source": ik["literature"], "reference_asset_sha256": ik["reference_asset_sha256"]}
    if p.hand_support == "knuckles":
        recipe["knuckle_technique"] = {"id": p.knuckle_technique,
            "grip": "palmar normals inward; radial axes forward along the floor",
            "max_axis_error_rad": float(np.pi / 6), "max_bent_elbow_flare_rad": float(np.pi / 6),
            "bottom_max_shoulder_above_elbow_m": .05,
            "interpretation": "declared engineering technique targets; native joint ranges unchanged; not clinical norms"}
    elif p.hand_support == "palms":
        from .hands import PALM_PLACEMENT_TOLERANCE_M
        recipe["palm_reference_check"] = {
            "references": "scenarios/pushup_palms/references.md",
            "support_landmark": "mean native palm pad centres projected onto the floor",
            "longitudinal_band": "between ipsilateral shoulder joint and caudal end of native Sternum mesh; body-relative floor heading",
            "placement_tolerance_m": PALM_PLACEMENT_TOLERANCE_M,
            "max_bottom_shoulder_above_elbow_m": .05,
            "max_finger_direction_error_rad": float(np.pi / 6),
            "interpretation": "Broad engineering rejection checks, not registered human kinematics or clinical norms. Legacy reach is retained for reproducibility and must fail placement."}
    dump(output / "model_recipe.json", recipe)
    dump(output / "initial_conditions.json", {"qpos": initial_qpos.tolist(), "qvel": "zero", "activation": "zero",
                                              "gravity_m_per_s2": model.opt.gravity.tolist(), "settling_s": .2})
    if wrist_samples:
        dump(output / "wrists.json", {"samples": wrist_samples, "ligament_forces": "not modeled",
                                       "moments": "ground contact wrench about wrist origin; not joint reaction or ligament tension"})
    atlas = [{"id": i, "name": model.actuator(i).name, "group": anatomical_group(model.actuator(i).name),
              "regions": regions[model.actuator(i).name],
              "mapping_evidence": "literal source identifier prefix; unmapped identifiers deliberately retained",
              "tendon_id": int(model.actuator_trnid[i, 0]), "actadr": int(model.actuator_actadr[i]),
              "dynamics": "MuJoCo muscle", "gainprm": model.actuator_gainprm[i].tolist(),
              "biasprm": model.actuator_biasprm[i].tolist(), "dynprm": model.actuator_dynprm[i].tolist()}
             for i in range(model.nu)]
    dump(output / "actuators.json", {"actuators": atlas, "groups_are_source_paths_not_independent_muscle_volumes": True})
    ranking = [{"actuator": a["name"], "group": a["group"], "mean_activation": float(activation_integral[i] / duration),
                "absolute_force_impulse_Ns": float(force_integral[i]), "signed_mechanical_work_J": float(work[i])}
               for i, a in enumerate(atlas)]
    ranking.sort(key=lambda r: r["absolute_force_impulse_Ns"], reverse=True)
    dump(output / "muscle_ranking.json", {"ranking_metric": "absolute actuator force impulse, not EMG or causal importance", "actuators": ranking})
    from .pectorals import write_pectorals
    write_pectorals(output, model, rows, muscle_samples, ranking, cycle_s)
    with (output / "series.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    fraction = contact_counts / (steps - round(.2 / p.timestep_s) + 1)
    middle = min(range(len(rows)), key=lambda i: rows[i]["chest_height_m"])
    elbows = np.array([[r["angle_rad"], r["left_elbow_rad"]] for r in rows])
    chest_excursion = rows[0]["chest_height_m"] - rows[middle]["chest_height_m"]
    gates = {
        "full_cycle_kinematics": bool(chest_excursion > .18 and np.min(elbows.max(axis=0)) > 1.4
            and np.max(elbows[0]) < .35 and np.max(elbows[-1]) < .4
            and abs(rows[-1]["chest_height_m"] - rows[0]["chest_height_m"]) < .06
            and .25 * len(rows) < middle < .75 * len(rows) and max_plank_deviation < .2),
        "four_supports": bool(min(fraction) > .95 and max_slip < (.0005 if p.hand_support != "legacy_point" else .06)),
        "numerical_bounds": bool(max_penetration < .005 and max_limit_hinge < .02 and max_limit_slide < .001
            and max_balance < 1e-4 and max_moment_balance < 1e-4 and max_transmission_error < 1e-8
            and max_friction_error < 1e-6),
    }
    if p.hand_support != "legacy_point":
        gates["stationary_supports"] = bool(max_slip < .0005)
    if p.hand_support == "knuckles":
        settled = [r for r in rows if r["time_s"] >= .2 - 1e-10]
        bent = [r for r in settled if min(r["angle_rad"], r["left_elbow_rad"]) > .6]
        gates["neutral_knuckle_grip"] = all(min(r[f"hand_{s}_{axis}_cosine"] for r in settled) > np.cos(np.pi / 6)
            for s in "rl" for axis in ("palm_inward", "radial_forward"))
        gates["tucked_elbows"] = bool(bent) and all(max(r[f"elbow_{s}_flare_rad"] for r in bent) < np.pi / 6 for s in "rl")
        gates["bottom_depth"] = all(rows[middle][f"shoulder_{s}_above_elbow_m"] < .05 for s in "rl")
    elif p.hand_support == "palms":
        from .hands import palm_placement_passes
        settled = [r for r in rows if r["time_s"] >= .2 - 1e-10]
        gates["reference_hand_placement"] = palm_placement_passes(settled)
        gates["forward_fingers"] = all(
            min(r[f"hand_{s}_fingers_forward_cosine"] for r in settled) > np.cos(np.pi / 6) for s in "rl")
        gates["bottom_depth"] = all(rows[middle][f"shoulder_{s}_above_elbow_m"] < .05 for s in "rl")
    if p.hand_support != "legacy_point":
        settled = [r for r in rows if r["time_s"] >= .2 - 1e-10]
        gates["hand_support_geometry"] = all(
            max(r[f"hand_{s}_support_tilt_rad"] for r in settled) < .1
            and np.mean([r[f"hand_{s}_bearing_points"] >= 2 for r in settled]) > .95 for s in "rl")
    if p.palm_technique == "chest_full":
        gates["elbow_extension"] = bool(max(np.max(elbows[0]), np.max(elbows[-1])) < .15)
        gates["wrist_extension_envelope"] = bool(max_wrist_extension <= np.pi / 2 + .01)
    acceptance = {k: "PASS" if v else "FAIL" for k, v in gates.items()}
    acceptance.update({"full_pushup": "PASS" if all(gates.values()) else "FAIL",
                       "muscle_driven": "PASS" if all(gates.values()) and p.control == "muscle" and max_external == 0 else "NOT_ACHIEVED",
                       "external_control": "USED" if p.control != "muscle" else "ABSENT",
                       "human_experimental_validation": "NOT_VALIDATED", "volumetric_anatomy_registration": "UNAVAILABLE"})
    acceptance["finger_dynamics"] = "RIGID_SOURCE_POSTURE" if p.hand_support != "legacy_point" else "NOT_MODELED"
    acceptance["wrist_ligaments"] = "NOT_MODELED"
    if p.palm_technique == "chest_full":
        acceptance["wrist_range_derivation"] = "LITERATURE_INFORMED_NOT_CALIBRATED"
    metrics_values = {"chest_excursion_m": chest_excursion, "chest_return_error_m": abs(rows[-1]["chest_height_m"] - rows[0]["chest_height_m"]),
        "max_support_slip_m": max_slip, "min_support_fraction": float(min(fraction)),
        "max_penetration_m": max_penetration, "max_hinge_limit_violation_rad": max_limit_hinge,
        "max_slide_limit_violation_m": max_limit_slide, "max_force_balance_error_N": max_balance,
        "max_moment_balance_error_Nm": max_moment_balance, "max_transmission_sum_error": max_transmission_error,
        "max_friction_violation_N": max_friction_error, "max_external_generalized_force": max_external,
        "max_plank_joint_deviation_rad": max_plank_deviation,
        "external_work_J": external_work}
    if p.palm_technique == "chest_full":
        metrics_values["max_wrist_shaft_extension_rad"] = max_wrist_extension
    if p.support_boundary == "fixed_points":
        metrics_values.update(max_support_point_displacement_m=max_slip, max_support_point_speed_m_per_s=max_anchor_speed,
                              support_constraint_work_J=support_work)
    if p.hand_support == "knuckles":
        metrics_values.update(max_bent_elbow_flare_rad=max((r[f"elbow_{s}_flare_rad"] for r in bent for s in "rl"), default=float(np.pi)),
            min_palm_inward_cosine=min(r[f"hand_{s}_palm_inward_cosine"] for r in settled for s in "rl"),
            min_radial_forward_cosine=min(r[f"hand_{s}_radial_forward_cosine"] for r in settled for s in "rl"),
            bottom_shoulder_above_elbow_m=max(rows[middle][f"shoulder_{s}_above_elbow_m"] for s in "rl"))
    elif p.hand_support == "palms":
        metrics_values.update(max_wrist_ahead_head_m=max(r[f"hand_{s}_ahead_head_m"] for r in settled for s in "rl"),
            max_wrist_ahead_shoulder_m=max(r[f"hand_{s}_ahead_shoulder_m"] for r in settled for s in "rl"),
            max_palm_shoulder_chest_gap_m=max(r[f"palm_{s}_shoulder_chest_gap_m"] for r in settled for s in "rl"),
            max_palm_ahead_shoulder_m=max(r[f"palm_{s}_ahead_shoulder_m"] for r in settled for s in "rl"),
            min_fingers_forward_cosine=min(r[f"hand_{s}_fingers_forward_cosine"] for r in settled for s in "rl"),
            bottom_shoulder_above_elbow_m=max(rows[middle][f"shoulder_{s}_above_elbow_m"] for s in "rl"))
    dump(output / "summary.json", {"acceptance": acceptance, "metrics": metrics_values, "support_fractions": dict(zip(PADS, fraction.tolist(), strict=True)),
                                   "key_indices": [0, middle, len(rows) - 1], "top_force_impulse": ranking[:20],
                                   "thresholds": {"min_chest_excursion_m": .18, "min_peak_bilateral_elbow_rad": 1.4,
                                      "max_initial_elbow_rad": .35, "max_final_elbow_rad": .4,
                                      "max_chest_return_error_m": .06, "min_four_support_fraction": .95,
                                      "max_support_displacement_m": .0005 if p.hand_support != "legacy_point" else .06, "max_plank_joint_deviation_rad": .2,
                                      "max_penetration_m": .005, "max_hinge_limit_violation_rad": .02,
                                      "max_slide_limit_violation_m": .001, "max_force_balance_error_N": 1e-4,
                                      "max_moment_balance_error_Nm": 1e-4, "max_transmission_sum_error": 1e-8,
                                      "max_friction_violation_N": 1e-6,
                                      **({"max_palm_shoulder_chest_gap_m": PALM_PLACEMENT_TOLERANCE_M}
                                         if p.hand_support == "palms" else {}),
                                      **({"max_top_elbow_rad": .15, "max_wrist_shaft_extension_rad": float(np.pi / 2 + .01)}
                                         if p.palm_technique == "chest_full" else {})}})
    if p.support_boundary == "fixed_points":
        dump(output / "support_stationarity.json", {"boundary": "ideal_sticking_point_constraints", "max_displacement_by_point_m": anchor_displacements,
             "max_contact_patch_displacement_by_pad_m": pad_displacements,
             "max_displacement_m": max_slip, "max_speed_m_per_s": max_anchor_speed, "constraint_work_J": support_work,
             "displacement_tolerance_m": .0005,
             "reaction_check": "native unilateral normals and per-limb aggregate Coulomb bound; all reactions included in Newton balance"})
    metadata = {"sample_interval_s": sample_interval, "control_interval_s": .01, "integration_timestep_s": p.timestep_s,
                "state_spec": int(state_spec), "joint_order": [model.joint(i).name for i in range(model.njnt)],
                "actuator_order": [a["name"] for a in atlas], "muscle_chunks": muscle_files,
                "mechanics": "Sparse J rows per actuator: generalized contribution=J_row*force_N; sum equals qfrc_actuator. Power=force_N*actuator_velocity; signed shortening work convention.",
                "force_sign": "signed MuJoCo tendon transmission force; tensile muscle forces are generally negative",
                "units": {"excitation": "1", "activation": "1", "force_N": "N", "length_m": "m", "velocity_m_per_s": "m/s", "power_W": "W",
                          "moment_values": "m/rad for hinge, m/m for slide; transmission derivative dL/dq"}}
    dump(output / "trajectory_metadata.json", metadata)
    dump(output / "contact_map.json", {"floor": floor, "pads": [{"name": n, "id": model.geom(n).id,
        "body": model.body(model.geom_bodyid[model.geom(n).id]).name, "pos_m": model.geom_pos[model.geom(n).id].tolist(),
        "radius_m": float(model.geom_size[model.geom(n).id, 0])} for n in pad_names], "source_self_collision": "retained",
        "floor_contact_scope": "only declared pad bitmasks, not complete body-floor collision"})
    units = {"m": "m", "rad": "rad", "N": "N", "Nm": "N*m", "J": "J", "W": "W", "s": "s"}
    metrics = [{"name": k, "value": v, "unit": units.get(k.rsplit("_", 1)[-1], "1")} for k, v in metrics_values.items()]
    for metric in metrics:
        if metric["name"] == "max_external_generalized_force":
            metric["unit"] = "N*m"
        elif metric["name"] == "max_transmission_sum_error":
            metric["unit"] = "componentwise N or N*m"
        elif metric["name"] == "max_support_point_speed_m_per_s":
            metric["unit"] = "m/s"
    return {"status": "computed", "metrics": metrics, "acceptance": acceptance,
            "citations": CITATIONS + ([{"title": "Kim et al. 2006, radiocarpal/midcarpal extension; engineering envelope, not calibration", "url": ik["literature"]}]
                                      if p.palm_technique == "chest_full" else []),
            "render": {"status": "not_requested", "render_backend": "none", "next": "render_result with saved states"},
            "integration_steps": steps, "simulation_time_s": duration, "timestep_s": p.timestep_s,
            "integrator": "mjINT_IMPLICITFAST", "initial_conditions": {"artifact": "initial_conditions.json", "reference": "reference.npz"},
        "model_derivation": recipe, "limitations": LIMITATIONS + ([
            "Prescribed sticking points restrict horizontal motion; free vertical numerical guides preserve unilateral floor normals. This is an ideal boundary condition, not calibrated deformable skin friction.",
            "Four unactuated 0.1 g vertical guides add small inertia/damping; actual guide reactions are included in force balance and aggregate per-limb Coulomb checks at every integration step."
        ] if p.support_boundary == "fixed_points" else []) + ([
            "Detailed hands use native manipulation meshes and muscle paths in rigid open/closed finger poses; no independent finger dynamics, ligament forces or tissue pressure.",
            "Left posture mirrors the source right hand with native mirrored meshes; primary hand mass/inertia retained. Hand actuator length ranges use the manipulation source where provided.",
            ("Full palms use a separately declared wrist envelope and stance; palms/knuckles are not an isolated causal comparison."
             if p.palm_technique == "chest_full" else "Palms and knuckles use different hand locations to remain within native wrist ranges; this is not an isolated causal comparison of support surface."),
            "Assisted muscle mode applies recorded bounded residual generalized joint torques in addition to genuine muscle forces; it is not pure muscle-driven dynamics."
        ] if p.hand_support != "legacy_point" else []) + ([
            "Only two wrist-extension coordinate bounds differ from the pinned model; the separate whole-shaft angle is checked at every integration step. Literature motivates this engineering envelope but does not calibrate the model's oblique hinges, coupling, muscle curves, ligaments or participant anatomy."
        ] if p.palm_technique == "chest_full" else []),
            "controller": {"mode": p.control, "root_actuation": False, "body_wrench": False, "kp": 600,
                           "kp_by_independent_joint": {model.joint(j).name: float(gains[j]) for j in active},
                           "external_torque_limit_Nm": 200 if p.control != "muscle" else 0,
                           "assistance": "bounded external residual after actual muscle force" if p.control == "assisted_muscle" else "none",
                           "palm_orientation_gain_Nm_per_rad": 10000 if p.hand_support == "palms" and p.support_boundary == "frictional" else 0,
                           "hand_orientation_kp_Nm_per_rad": 3000 if p.support_boundary == "fixed_points" else 0,
                           "hand_orientation_kd_Nms_per_rad": 30 if p.support_boundary == "fixed_points" else 0,
                           "gravity_feedforward": "least-squares static load sharing; predicted loads are not measured pressures" if p.support_boundary == "fixed_points" else "none",
                           "joint_feedback_interval_s": p.timestep_s,
                           "muscle_allocation": "300 projected accelerated-gradient iterations, bounds [0,1], ridge 1e-5; 100 Hz",
                           "reference": f"0.2 s settle, {cycle_s:g} s sine-squared flexion cycle, 0.2 s hold"},
            "counts": {"nq": model.nq, "nv": model.nv, "actuators": model.nu, "tendons": model.ntendon, "equality_constraints": model.neq},
            "checks": [{"name": n, "status": "pass"} for n in ("finite_state", "zero_engine_warnings", "activation_bounds", "elapsed_time", "no_root_actuation")],
            "time_series": {"artifact_id": "series.csv", "axis": "time_s", "units": {k: units.get(k.rsplit("_", 1)[-1], "1") for k in rows[0]},
                            "definition": "State-aligned full-model integrated dynamics; acceptance is separate from computed status."},
            "muscle_outputs": {"metadata": "trajectory_metadata.json", "actuators": "actuators.json", "ranking": "muscle_ranking.json", "chunks": muscle_files},
            "contact_outputs": {"index": "contacts.json", "support": "support.json"}}
