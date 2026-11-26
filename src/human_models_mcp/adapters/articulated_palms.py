"""Experimental source-joint palms and bounded contact patches."""

import xml.etree.ElementTree as ET

import numpy as np

FLOOR_BIT = 8
PROFILE = "articulated_palms_v1"
# Fit to the existing source contact capsules in the documented flat-palm pose.
FLOOR_LOCAL_Z = -.022
FINGER_REST = {
    "cmc_flexion": -.3100, "cmc_abduction": -.3174, "mp_flexion": .0870, "ip_flexion": .2836,
    "2mcp_abduction": -.1090, "2mcp_flexion": .4348,
    "3mcp_abduction": -.0462, "3mcp_flexion": .3690,
    "4cmc_flexion": .2000, "4mcp_abduction": .0481, "4mcp_flexion": .2170,
    "5mcp_abduction": .1384, "5mcp_flexion": -.0320,
}
PALM_PATCHES = {
    "capitate": ("heel", [0., -.009], .011),
    "trapezium": ("thenar", [.021, -.026], .011),
    "hamate": ("hypothenar", [-.018, -.027], .011),
    "2mc": ("distal_radial", [.014, -.059], .010),
    "3mc": ("distal", [0, -.065], .010),
    "4mc_new": ("distal_ulnar", [-.016, -.061], .010),
}
FINGER_CAPSULES = {
    "proximal_thumb_skin_r": "thumbprox", "distal_thumb_skin_r": "thumbdist",
    **{f"{i}{part}ph_skin_r": f"{i}{part}ph" + ("_new" if i >= 4 else "")
       for i in range(2, 6) for part in ("prox", "mid", "dist")},
}


def numbers(values):
    return " ".join(str(float(v)) for v in values)


def rotation(mj, quat):
    result = np.empty(9)
    mj.mju_quat2Mat(result, quat / np.linalg.norm(quat))
    return result.reshape(3, 3)


def quaternion(mj, matrix):
    result = np.empty(4)
    mj.mju_mat2Quat(result, np.ascontiguousarray(matrix).ravel())
    return numbers(result)


def parallel_axis(mass, x):
    return mass * (np.eye(3) * (x @ x) - np.outer(x, x))


def add_bodies(mj, root, target, model, data, hand, descendants, side, reflect):
    """Retain parent mass, centre and inertia at the neutral assembled pose."""
    bodies = {hand: target}
    original = target.find("inertial")
    mass = float(original.get("mass"))
    com = np.fromstring(original.get("pos"), sep=" ")
    imat = rotation(mj, np.fromstring(original.get("quat"), sep=" "))
    inertia = imat @ np.diag(np.fromstring(original.get("diaginertia"), sep=" ")) @ imat.T
    transform = reflect @ data.xmat[hand].reshape(3, 3).T
    child_ids = sorted(descendants - {hand})
    child_mass = model.body_mass[child_ids]
    centres = (data.xipos[child_ids] - data.xpos[hand]) @ transform.T
    child_i = np.zeros((3, 3))
    for b, centre in zip(child_ids, centres, strict=True):
        axes = transform @ data.ximat[b].reshape(3, 3)
        child_i += axes @ np.diag(model.body_inertia[b]) @ axes.T + parallel_axis(model.body_mass[b], centre)
    # Allocate a common fraction of donor inertials while leaving a positive physical palm tensor.
    alpha = .25
    remainder_mass = mass - alpha*sum(child_mass)
    remainder_com = (mass*com - alpha*(child_mass @ centres))/remainder_mass
    remainder_i = inertia + parallel_axis(mass, com) - alpha*child_i - parallel_axis(remainder_mass, remainder_com)
    values, axes = np.linalg.eigh(remainder_i)
    if min(values) <= 0 or max(values)*2 >= sum(values):
        raise ValueError("donor inertials do not fit the primary hand mass distribution")
    axes[:, 2] *= np.linalg.det(axes)
    original.attrib.update(mass=str(remainder_mass), pos=numbers(remainder_com),
                           diaginertia=numbers(values), quat=quaternion(mj, axes))
    for b in child_ids:
        bid = int(model.body_parentid[b])
        name = "hand_" + side + "_" + model.body(b).name
        body = bodies[b] = ET.SubElement(bodies[bid], "body", name=name, pos=numbers(reflect @ model.body_pos[b]),
                                        quat=quaternion(mj, reflect @ rotation(mj, model.body_quat[b]) @ reflect))
        if model.body_mass[b] > 0:
            ET.SubElement(body, "inertial", mass=str(alpha * model.body_mass[b]),
                          pos=numbers(reflect @ model.body_ipos[b]),
                          quat=quaternion(mj, reflect @ rotation(mj, model.body_iquat[b]) @ reflect),
                          diaginertia=numbers(alpha*model.body_inertia[b]))
        for j in range(model.body_jntadr[b], model.body_jntadr[b]+model.body_jntnum[b]):
            ET.SubElement(body, "joint", name=name_joint(side, model.joint(j).name), type="hinge",
                          pos=numbers(reflect @ model.jnt_pos[j]), axis=numbers(reflect @ model.jnt_axis[j] * reflect[2, 2]),
                          range=numbers(model.jnt_range[j]), solimplimit=numbers(model.jnt_solimp[j]),
                          solreflimit=numbers(model.jnt_solref[j]), stiffness=str(model.jnt_stiffness[j]),
                          springref=str(model.qpos_spring[model.jnt_qposadr[j]]),
                          damping=str(model.dof_damping[model.jnt_dofadr[j]]),
                          armature=str(model.dof_armature[model.jnt_dofadr[j]]))
    ET.SubElement(root.find("equality"), "joint", name=name_joint(side,"4_5_cmc_source_coupling"),
                  joint1=name_joint(side,"CMC5_r1"), joint2=name_joint(side,"4cmc_flexion"),
                  polycoef="0 2.72 0 0 0", solimp=".9999 .9999")
    return bodies


def name_joint(side, name):
    return "digit_" + side + "_" + name


def add_patches(mj, target, model, data, hand, bodies, side, reflect):
    bare = {"contype": str(FLOOR_BIT), "conaffinity": "0", "mass": "0", "rgba": "0 0 0 0",
            "group": "5", "condim": "3", "solref": ".012 1", "solimp": ".85 .97 .004 .5 2",
            "margin": "0", "gap": "0"}
    posed = mj.MjData(model)
    posed.qpos[:] = data.qpos
    for name, value in FINGER_REST.items():
        posed.qpos[model.joint(name).qposadr[0]] = value
    posed.qpos[model.joint("CMC5_r1").qposadr[0]] = 2.72 * FINGER_REST["4cmc_flexion"]
    mj.mj_kinematics(model, posed)
    for source, (_, xy, radius) in PALM_PATCHES.items():
        position = np.asarray([*xy, FLOOR_LOCAL_Z + radius])
        body = target
        if source == "4mc_new":
            b = model.geom(source).bodyid[0]
            body = bodies[b]
            world = posed.xpos[hand] + posed.xmat[hand].reshape(3,3) @ position
            position = posed.xmat[b].reshape(3,3).T @ (world - posed.xpos[b])
        ET.SubElement(body, "geom", name=f"palm_{side}_surface_hand_detail_{side}_{source}",
                      type="sphere", pos=numbers(reflect @ position), size=str(radius), **bare)
    for capsule, source in FINGER_CAPSULES.items():
        g = model.geom(capsule).id
        b = int(model.geom_bodyid[g])
        ET.SubElement(bodies[b], "geom", name=f"palm_{side}_surface_hand_detail_{side}_{source}",
                      type="capsule", pos=numbers(reflect @ model.geom_pos[g]),
                      quat=quaternion(mj, reflect @ rotation(mj, model.geom_quat[g]) @ reflect),
                      size=numbers(model.geom_size[g,:2]), **bare)


def region(geom_name):
    source = geom_name.split("_surface_", 1)[-1][14:]
    if source in PALM_PATCHES:
        return PALM_PATCHES[source][0]
    if source.startswith("thumb"):
        return "digit_1"
    if source[:1] in "2345" and source:
        return "digit_" + source[0]
    return None


def align_reference(mj, model, poses):
    """Align the native toes and distributed palm patches before any time integration."""
    from .contact_geometry import mesh_vertices

    d = mj.MjData(model)
    toe_meshes = [model.geom(side + "_bofoot").id for side in "rl"]
    points = [mesh_vertices(model, g) for g in toe_meshes]
    palm_patches = [model.geom(f"palm_{side}_surface_hand_detail_{side}_{bone}").id
                    for side in "rl" for bone in PALM_PATCHES]
    pitch = model.joint("pelvis_tilt").id
    for pose in poses:
        d.qpos[:] = pose

        def heights():
            mj.mj_kinematics(model, d)
            toe_z = np.mean([d.geom_xpos[g, 2] + (v @ d.geom_xmat[g, 6:9]).min()
                             for g, v in zip(toe_meshes, points, strict=True)])
            palm_z = np.mean(d.geom_xpos[palm_patches, 2] - model.geom_size[palm_patches, 0])
            return toe_z, palm_z - toe_z

        for _ in range(2):
            _, error = heights()
            d.qpos[pitch] += .0001
            _, moved = heights()
            d.qpos[pitch] -= .0001 + error * .0001 / (moved - error)
        toe_z, _ = heights()
        pose[:] = d.qpos
        pose[model.joint("pelvis_ty").id] -= toe_z


def regional_forces(mj, model, data, floor, mapping):
    by_side = {side: dict.fromkeys((*[r[0] for r in PALM_PATCHES.values()],
                                  *["digit_" + str(i) for i in range(1,6)]), 0.) for side in "rl"}
    wrench = np.zeros(6)
    for i in range(data.ncon):
        contact = data.contact[i]
        if floor not in contact.geom:
            continue
        other = int(contact.geom[int(contact.geom[0] == floor)])
        if other in mapping:
            mj.mj_contactForce(model, data, i, wrench)
            side, name = mapping[other]
            by_side[side][name] += float(wrench[0])
    return by_side


def flat_wrist_targets(mj, model, data):
    targets = {}
    for side in "rl":
        r = data.xmat[model.body("hand_" + side).id].reshape(3,3)
        normal = np.array([0., 0., 1. if side == "r" else -1.])
        radial = r[:, 0].copy()
        radial[2] = 0.
        radial /= np.linalg.norm(radial)
        q = np.empty(4)
        mj.mju_mat2Quat(q, np.column_stack((radial, np.cross(normal, radial), normal)).ravel())
        targets[side] = q
    return targets
