"""Declared ideal sticking support points, with measured constraint reactions."""

import hashlib
import json
from pathlib import Path

import numpy as np

from .contact import hull_xy, inside_hull


def fixed_reference_poses(mj, model, data, yaw=0, forward_shift=0, peak_elbow=1.6, initial_elbow=.2, initial_only=False,
                          tucked=False, hand_half_width=None, forward_palms=False, palm_level=None):
    from .pushup import ARM, couple
    if palm_level is not None and (palm_level not in ("shoulders", "chest") or not initial_only):
        raise ValueError("palm body level is an initial placement target; freeze floor positions before a cycle")
    q = model.key_qpos[0].copy()
    def forward(qpos):
        data.qpos[:] = qpos
        couple(model, data.qpos)
        mj.mj_kinematics(model, data)
        mj.mj_comPos(model, data)
        delta = data.site_xpos[model.site("anchor_toe_r").id] - data.site_xpos[model.site("material_toe_r").id]
        data.qpos[:3] += [-delta[1], delta[2], delta[0]]
        mj.mj_kinematics(model, data)
        mj.mj_comPos(model, data)
        return data.qpos.copy()
    q = forward(q)
    rotations = {s: data.xmat[model.body("hand_" + s).id].copy() for s in "rl"}
    palms = mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM, "palm_r_2") >= 0
    for side in "rl":
        rotation = rotations[side].reshape(3, 3)
        normal = rotation @ ([0, 0, -1 if side == "r" else 1] if palms else [0, -1, 0])
        cross = np.cross(normal, [0, 0, -1])
        skew = np.array([[0, -cross[2], cross[1]], [cross[2], 0, -cross[0]], [-cross[1], cross[0], 0]])
        rotations[side] = ((np.eye(3) + skew + skew @ skew / (1 - normal[2])) @ rotation).reshape(9)
    for side in "rl":
        angle = yaw if side == "r" else -yaw
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
        rotations[side] = (rotation @ rotations[side].reshape(3, 3)).reshape(9)
    if tucked:
        rotations = {s: np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]]).reshape(9) for s in "rl"}
        hand_half_width = .2
    if forward_palms:
        rotations = {"r": np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]]).reshape(9),
                     "l": np.array([[0., -1, 0], [-1, 0, 0], [0, 0, -1]]).reshape(9)}
    positions = {s: data.xpos[model.body("hand_" + s).id].copy() for s in "rl"}
    palm_offsets = {}
    for side in "rl":
        positions[side][0] += forward_shift
        if hand_half_width is not None:
            positions[side][1] = -hand_half_width if side == "r" else hand_half_width
        pads = [i for i in range(model.ngeom) if model.geom(i).name.startswith("palm_" + side)]
        palm_offsets[side] = float((rotations[side].reshape(3, 3) @ np.mean(model.geom_pos[pads], axis=0))[0])
        positions[side][2] = float(model.geom_size[pads[0], 0] - np.mean((rotations[side].reshape(3, 3) @ model.geom_pos[pads].T)[2]))
        positions[side][2] += q[model.jnt_qposadr[model.joint("support_height_palm_" + side).id]]
    names = [n + "_" + s for s in "rl" for n in (*ARM, "ankle_angle", "mtp_angle", "hip_flexion")]
    indices = [3] + [model.joint(n).id for n in names] + [36, 39]
    low, high = model.jnt_range[indices, 0] + 1e-4, model.jnt_range[indices, 1] - 1e-4
    for k, j in enumerate(indices):
        if j in (6, 21, 36, 39):
            low[k], high[k] = -.1, .1
    def residual(qpos, elbow):
        actual = forward(qpos)
        values = list((data.site_xpos[model.site("material_toe_l").id] - data.site_xpos[model.site("anchor_toe_l").id]) * 5)
        for s in "rl":
            bid = model.body("hand_" + s).id
            target = positions[s].copy()
            if palm_level is not None:
                level = (data.xanchor[model.joint("shoulder_elv_" + s).id, 0] if palm_level == "shoulders"
                         else data.geom_xpos[model.geom("Sternum").id, 0])
                target[0] = level - palm_offsets[s]
            values.extend((data.xpos[bid] - target) * 5)
            values.extend((data.xmat[bid] - rotations[s]) * .7)
            values.append((actual[model.joint("elbow_flexion_" + s).id] - elbow) * .6)
            if tucked:
                values.append((data.xanchor[model.joint("elbow_flexion_" + s).id, 1]
                              - data.xanchor[model.joint("shoulder_elv_" + s).id, 1]) * 3)
        return np.array(values)
    poses, errors = [], []
    for elbow in np.linspace(initial_elbow, peak_elbow, 1 if initial_only else 17):
        for _ in range(400):
            error = residual(q, elbow)
            if np.linalg.norm(error) < 1e-6:
                break
            jac = np.empty((len(error), len(indices)))
            for col, joint in enumerate(indices):
                probe = q.copy()
                probe[joint] += 1e-5
                jac[:, col] = (residual(probe, elbow) - error) / 1e-5
            delta = -jac.T @ np.linalg.solve(jac @ jac.T + 1e-5 * np.eye(len(error)), error)
            for _ in range(len(indices)):
                blocked = ((q[indices] <= low + 1e-8) & (delta < 0)) | ((q[indices] >= high - 1e-8) & (delta > 0))
                if not blocked.any():
                    break
                jac[:, blocked] = 0
                delta = -jac.T @ np.linalg.solve(jac @ jac.T + 1e-5 * np.eye(len(error)), error)
            for scale in (1, .5, .1, .01):
                probe = q.copy()
                probe[indices] = np.clip(q[indices] + scale * np.clip(delta, -.1, .1), low, high)
                if np.linalg.norm(residual(probe, elbow)) < np.linalg.norm(error):
                    q = probe
                    break
            else:
                break
        errors.append(float(np.linalg.norm(residual(q, elbow))))
        if errors[-1] > 1e-4:
            raise ValueError(f"fixed-support reference cannot close at elbow={elbow}: {errors[-1]}")
        poses.append(forward(q))
    return np.array(poses), {"method": "closed-chain bounded IK with fixed hands/toe points and native ankle articulation", "max_residual": max(errors)}


def chest_palm_reference(mj, model):
    """Synthetic bounded-IK seed and partial cycle; not measured human motion."""
    from .pushup import ARM
    indices = [3] + [model.joint(n + "_" + s).id for s in "rl"
                     for n in (*ARM, "ankle_angle", "mtp_angle", "hip_flexion")] + [36, 39]
    original = model.key_qpos[0].copy()
    seed = original.copy()
    seed[indices] = [-1.444885952836711, -.3359272262103215, .7755242672424552,
        -.3214128533729174, 1.9076504121277973, .5653429153510918, -.09524932198226622,
        -.5996441058447882, .06840504311072439, -.4779189391599489, -.09590675099671277,
        -.3359059472324952, .7755882894632774, -.3211341412988296, 1.9078560395151316,
        .5656541195128423, -.09485204099591639, -.5998019846779769, .06723564373314982,
        -.48413650007954523, -.09577814917984617, -.03296114074652789, .02812154285641298]
    model.key_qpos[0] = seed
    try:
        poses, info = fixed_reference_poses(mj, model, mj.MjData(model),
            initial_elbow=1.90775, peak_elbow=1.4, forward_palms=True)
    finally:
        model.key_qpos[0] = original
    return poses[::-1].copy(), {**info, "variant": "wide palms at chest level",
        "partial_range": True, "initial_elbow_rad": 1.4, "peak_elbow_rad": 1.90775,
        "reference_hand_width_m": .7, "seed": "bounded native-model IK, not motion capture",
        "native_joint_ranges_unchanged": True}


def full_palm_reference(mj, model, initial_only=False):
    """Replay checked synthetic IK targets; all later dynamics still use mj_step."""
    from .hands import palm_placement_passes, measure_palm_technique, wrist_shaft_extension
    from .pushup import couple

    raw = Path(__file__).with_name("palms_full_reference_v1.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != "a4ea41d27ebcca8fc71c065587b1895325dad0f97ee1e01b9719ed57ee8423c6":
        raise ValueError("immutable full-palm reference differs from its pinned SHA-256")
    reference = json.loads(raw)
    values = np.asarray(reference["joint_values_rad"], dtype=float)
    indices = [int(model.joint(n).qposadr[0]) for n in reference["joint_names"]]
    if values.shape != (33, len(indices)) or not np.isfinite(values).all():
        raise ValueError("invalid full-palm reference shape or nonfinite target")
    data, poses, closure = mj.MjData(model), [], 0.0
    for row in values[:1] if initial_only else values:
        data.qpos[:] = model.key_qpos[0]
        data.qpos[indices] = row
        couple(model, data.qpos)
        mj.mj_kinematics(model, data)
        delta = data.site_xpos[model.site("anchor_toe_r").id] - data.site_xpos[model.site("material_toe_r").id]
        data.qpos[:3] += [-delta[1], delta[2], delta[0]]
        mj.mj_kinematics(model, data)
        if not palm_placement_passes([measure_palm_technique(model, data)]):
            raise ValueError("full-palm reference leaves the shoulder/chest band")
        if max(wrist_shaft_extension(model, data, s) for s in "rl") > reference["shaft_extension_cap_rad"]:
            raise ValueError("full-palm reference exceeds its geometric wrist envelope")
        limited = model.jnt_limited[:85].astype(bool)
        violation = np.maximum(model.jnt_range[:85, 0] - data.qpos[:85], data.qpos[:85] - model.jnt_range[:85, 1])
        if np.max(violation[limited]) > 1e-8:
            raise ValueError("full-palm reference exceeds a model joint bound")
        if not initial_only:
            closure = max(closure, *(float(np.linalg.norm(data.site_xpos[model.site("material_" + n).id]
                - data.site_xpos[model.site("anchor_" + n).id])) for n in ("palm_r", "palm_l", "toe_r", "toe_l")))
        poses.append(data.qpos.copy())
    if closure > 1e-6:
        raise ValueError("full-palm reference does not close its fixed support points")
    info = {k: v for k, v in reference.items() if k != "joint_values_rad"}
    info.update(reference_asset_sha256=digest, reference_asset="palm_reference_input.json", max_support_closure_m=closure)
    return np.array(poses), info


def tucked_knuckle_start(mj, model):
    data = mj.MjData(model)
    mj.mj_resetDataKeyframe(model, data, 0)
    mj.mj_forward(model, data)
    rotation = data.xmat[model.body("hand_r").id].reshape(3, 3)
    angle = np.arctan2(rotation[1, 0], rotation[0, 0])
    width = abs(data.xpos[model.body("hand_r").id, 1])
    # Turn incrementally to remain on the same bounded IK branch.
    for step in range(1, 17):
        poses, _ = fixed_reference_poses(mj, model, data, yaw=-angle / 16,
            hand_half_width=width + (.2 - width) * step / 16, initial_elbow=.2, initial_only=True)
        model.key_qpos[0] = poses[0]
    poses, _ = fixed_reference_poses(mj, model, data, forward_shift=-.08, tucked=True, initial_elbow=.2, initial_only=True)
    return poses[0]


def add_fixed_supports(mj, spec, model, data, qpos):
    data.qpos[:] = qpos
    mj.mj_forward(model, data)
    anchors = []
    for name in ("palm_r", "palm_l", "toe_r", "toe_l"):
        gids = [g for g in range(model.ngeom) if model.geom(g).name == name or model.geom(g).name.startswith(name + "_")]
        bid = int(model.geom_bodyid[gids[0]])
        points = data.geom_xpos[gids].copy()
        if name.startswith("palm_"):
            points[:, 2] -= model.geom_size[gids, 0]
        point = np.mean(points, axis=0)
        local = data.xmat[bid].reshape(3, 3).T @ (point - data.xpos[bid])
        point[2] = float(model.geom_size[gids[0], 0]) if name.startswith("toe_") else 0
        anchors.append({"geom": name, "body": model.body(bid).name,
                        "local_point_m": local.tolist(), "world_anchor_m": point.tolist()})
    install_fixed_supports(mj, spec, anchors)
    return anchors


def install_fixed_supports(mj, spec, anchors):
    for a in anchors:
        name = a["geom"]
        spec.body(a["body"]).add_site(name="material_" + name, pos=a["local_point_m"], size=[.001, 0, 0], group=5)
        guide = spec.worldbody.add_body(name="support_guide_" + name, pos=a["world_anchor_m"])
        guide.mass, guide.inertia, guide.explicitinertial = .0001, [1e-8] * 3, True
        # shortcut: 0.1 g guides meet the source compiler bound; replace with planar constraints if this inertia matters.
        guide.add_joint(name="support_height_" + name, type=mj.mjtJoint.mjJNT_SLIDE, axis=[0, 0, 1], limited=False, damping=.01, armature=0, stiffness=0)
        guide.add_site(name="anchor_" + name, pos=[0, 0, 0], size=[.001, 0, 0], group=5)
        eq = spec.add_equality(name="ground_" + name, type=mj.mjtEq.mjEQ_CONNECT,
                              objtype=mj.mjtObj.mjOBJ_SITE, name1="material_" + name, name2="anchor_" + name)
        eq.solref[:] = [.001, 1]
        eq.solimp[:] = [.9999, .9999, .001, .5, 2]


def fixed_support_command(mj, model, data, poses, active, orientations):
    """Joint feedback plus gravity/load-sharing feedforward; no root actuation."""
    from .pushup import target_pose, coordinate_tangent
    reference = target_pose(poses, float(data.time), 4.0)
    gains = np.full(model.nq, 3500.0)
    gains[45:85] = 2000
    gains[[15, 16, 17, 30, 31, 32]] = 0
    tangent = coordinate_tangent(model, data, active)
    desired = gains[active] * (reference[active] - data.qpos[active])
    names = ("palm_r", "palm_l", "toe_r", "toe_l")
    points = np.array([data.site_xpos[model.site("material_" + n).id] for n in names])
    mass = model.body_subtreemass[model.body("pelvis").id]
    loads = np.linalg.lstsq(np.vstack((np.ones(4), points[:, 0], points[:, 1])),
                           mass * 9.81 * np.r_[1, data.subtree_com[model.body("pelvis").id, :2]], rcond=None)[0]
    feedforward = data.qfrc_bias.copy()
    for name, normal in zip(names, loads, strict=True):
        linear = np.zeros((3, model.nv))
        mj.mj_jacSite(model, data, linear, None, model.site("material_" + name).id)
        feedforward -= linear[2] * normal
    desired += tangent.T @ feedforward
    for side in "rl":
        body = model.body("hand_" + side).id
        error = np.zeros(3)
        mj.mju_subQuat(error, orientations[side], data.xquat[body])
        angular = np.zeros((3, model.nv))
        mj.mj_jacBody(model, data, None, angular, body)
        desired += (angular @ tangent).T @ (3000 * (data.xmat[body].reshape(3, 3) @ error) - 30 * angular @ data.qvel)
    return np.clip(desired, -200, 200)


def fixed_reactions(mj, model, data):
    reactions = []
    for eq in range(model.neq):
        name = model.equality(eq).name
        if not name.startswith("ground_"):
            continue
        pad = name.removeprefix("ground_")
        rows = np.flatnonzero((data.efc_type == mj.mjtConstraint.mjCNSTR_EQUALITY) & (data.efc_id == eq))
        if len(rows) not in (0, 3):
            raise ValueError("fixed support must retain its three positional constraint rows")
        sid, anchor = model.site("material_" + pad).id, model.site("anchor_" + pad).id
        force = data.efc_force[rows].copy() if len(rows) else np.zeros(3)
        linear = np.zeros((3, model.nv))
        mj.mj_jacSite(model, data, linear, None, sid)
        velocity = linear @ data.qvel
        reactions.append({"geom": pad, "geom_id": model.geom(pad).id,
                          "position_m": data.site_xpos[sid].tolist(), "material_point_m": data.site_xpos[sid].tolist(), "anchor_m": data.site_xpos[anchor].tolist(),
                          "force_world_N": force.tolist(), "normal_force_N": 0.0,
                          "guide_vertical_force_N": float(force[2]),
                          "displacement_m": float(np.linalg.norm(data.site_xpos[sid, :2] - data.site_xpos[anchor, :2])),
                          "speed_m_per_s": float(np.linalg.norm(velocity[:2])), "power_W": float(force @ velocity),
                          "mechanism": "ideal_sticking_point_constraint", "equality_id": eq})
    return reactions


def measure_fixed_supports(mj, model, data, sample, friction):
    from .contact import measure_contacts
    force, moment, records, support, native_violation = measure_contacts(mj, model, data, model.geom("floor").id, sample, allowed_prefixes=("palm_", "toe_"))
    reactions = fixed_reactions(mj, model, data)
    points = []
    by_geom = {r["geom"]: np.array(r["force_world_N"]) for r in reactions}
    for r in records:
        if r["floor_contact"]:
            name = model.geom(r["geom1"] if r["geom0"] == model.geom("floor").id else r["geom0"]).name
            sign = 1 if r["geom0"] == model.geom("floor").id else -1
            group = next(g for g in by_geom if name == g or name.startswith(g + "_"))
            by_geom[group] += sign * np.array(r["force_on_geom1_world_N"])
            if r["normal_force_N"] > 1e-6:
                points.append(r["position_m"])
    violation = native_violation
    for r in reactions:
        f, point = np.array(r["force_world_N"]), np.array(r["position_m"])
        force += f
        moment += np.cross(point - data.subtree_com[model.body("pelvis").id], f)
        total = by_geom[r["geom"]]
        violation = max(violation, float(np.linalg.norm(total[:2]) - friction * total[2]), -float(total[2]))
        records.append({**r, "sample": sample, "time_s": float(data.time), "floor_contact": 1,
                        "gap_m": float(point[2]), "active": 1})
    polygon, area = hull_xy(points)
    origin_moment = moment + np.cross(data.subtree_com[model.body("pelvis").id], force)
    cop = [-origin_moment[1] / force[2], origin_moment[0] / force[2]] if force[2] > 1e-6 else None
    support = {"sample": sample, "time_s": float(data.time), "polygon_xy_m": polygon, "area_m2": area,
               "com_world_m": data.subtree_com[model.body("pelvis").id].tolist(), "cop_xy_m": cop,
               "com_projection_inside": inside_hull(data.subtree_com[model.body("pelvis").id], polygon, area),
               "cop_inside": inside_hull(cop, polygon, area) if cop else None,
               "boundary": "ideal_sticking_points", "anchors": reactions}
    return force, moment, records, support, violation
