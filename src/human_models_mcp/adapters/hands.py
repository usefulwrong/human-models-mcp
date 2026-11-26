"""Source-derived rigid finger postures and measured wrist mechanics, not ligament tissue."""

import copy
import xml.etree.ElementTree as ET

import numpy as np

from ..registry import home

HAND_MUSCLES = ("ECRL", "ECRB", "ECU", "FCR", "FCU", "PL", "FDSL", "FDSR", "FDSM", "FDSI",
                "FDPL", "FDPR", "FDPM", "FDPI", "EDCL", "EDCR", "EDCM", "EDCI", "EDM", "EIP", "EPL", "EPB", "FPL", "APL")
PALM_PLACEMENT_TOLERANCE_M = .05


def source_hand(support):
    import mujoco as mj

    spec = mj.MjSpec.from_file(str(home() / "models/ms_human_700/MS-Human-700-Manipulation.xml"))
    model = spec.compile()
    data = mj.MjData(model)
    posture = {}
    for j in range(model.njnt):
        name = model.joint(j).name
        if name.startswith(tuple(str(i) for i in range(2, 6))) and any(part in name for part in ("mcp_flexion", "pm_flexion", "md_flexion")):
            value = (1.35 if "mcp" in name else 1.4 if "pm_" in name else 1.1) if support == "knuckles" else 0.0
        elif name in ("cmc_flexion", "cmc_abduction", "mp_flexion", "ip_flexion"):
            value = {"cmc_flexion": .15, "cmc_abduction": .25, "mp_flexion": .6, "ip_flexion": .8}[name] if support == "knuckles" else 0.0
        else:
            continue
        if not model.jnt_range[j, 0] <= value <= model.jnt_range[j, 1]:
            raise ValueError("finger pose exceeds the upstream joint range: " + name)
        data.qpos[model.jnt_qposadr[j]] = value
        posture[name] = value
    mj.mj_forward(model, data)
    return mj, spec, model, data, posture


def configure_hands(primary, support, *, articulated=False):
    """Install source finger geometry and tendon routes with the requested joint model."""
    mj, source, model, data, posture = source_hand(support)
    root = ET.fromstring(primary.to_xml())
    if articulated:
        from .articulated_palms import FINGER_CAPSULES, PALM_PATCHES, add_bodies, add_patches

        root.find("./keyframe/key").attrib.pop("qpos", None)
    raw = ET.fromstring(source.to_xml())
    hand = model.body("capitate").id
    hand_rotation = data.xmat[hand].reshape(3, 3)
    descendants = {hand}
    for b in range(hand + 1, model.nbody):
        if model.body_parentid[b] in descendants:
            descendants.add(b)
    raw_geoms = {e.get("name"): e for e in raw.findall(".//body/geom")}
    raw_sites = {e.get("name"): e for e in raw.findall(".//body/site")}
    anchors = {"index": "2proxph", "middle": "3proxph", "little": "5proxph"}
    points = {n: hand_rotation.T @ (data.xpos[model.body(b).id] - data.xpos[hand]) for n, b in anchors.items()}
    # The pads are declared mechanical thickness offsets from source bony landmarks.
    if support == "palms":
        centers = np.array([[0, -.015, 0], points["index"], points["little"]])
        centers[:, 2] = -.028
    else:
        centers = np.array([points["index"], points["middle"]])
        centers[:, 1] = min(centers[:, 1]) - .014
    added_bones, rerouted = [], []
    for side in "rl":
        reflection = np.diag([1, 1, 1 if side == "r" else -1])
        target_hand = root.find(f".//body[@name='hand_{side}']")
        for element in list(target_hand.findall("geom")):
            if element.get("class") == "bone":
                target_hand.remove(element)
        bodies = (add_bodies(mj, root, target_hand, model, data, hand, descendants, side, reflection)
                  if articulated else dict.fromkeys(descendants, target_hand))
        def transformed(element, bid, name):
            value = copy.deepcopy(element)
            body_rotation = data.xmat[bid].reshape(3, 3)
            local = np.fromstring(value.get("pos", "0 0 0"), sep=" ")
            frame = bid if articulated else hand
            rotation = data.xmat[frame].reshape(3, 3)
            position = rotation.T @ (data.xpos[bid] + body_rotation @ local - data.xpos[frame])
            quat = np.fromstring(value.get("quat", "1 0 0 0"), sep=" ")
            mat = np.empty(9)
            mj.mju_quat2Mat(mat, quat)
            matrix = reflection @ rotation.T @ body_rotation @ mat.reshape(3, 3) @ reflection
            mj.mju_mat2Quat(quat, matrix.reshape(9))
            value.set("name", name)
            value.set("pos", " ".join(map(str, reflection @ position)))
            value.set("quat", " ".join(map(str, quat)))
            value.attrib.pop("euler", None)
            return value
        for gid in range(model.ngeom):
            if model.geom_bodyid[gid] not in descendants:
                continue
            element = raw_geoms.get(model.geom(gid).name)
            if element is None or element.get("class") != "bone":
                continue
            new = transformed(element, int(model.geom_bodyid[gid]), f"hand_detail_{side}_{element.get('name')}")
            if side == "l":
                mirrored = raw_geoms.get(element.get("name") + "_mirror")
                if mirrored is None:
                    raise ValueError("upstream mirrored hand mesh missing: " + element.get("name"))
                new.set("mesh", mirrored.get("mesh"))
            if articulated:
                new.set("mass", "0")
            bodies[int(model.geom_bodyid[gid])].append(new)
            added_bones.append(new.get("name"))
        copied = set()
        tendons = {e.get("name"): e for e in raw.findall("./tendon/spatial")}
        for muscle in HAND_MUSCLES:
            original_name = muscle + "_" + side + "_tendon"
            target = root.find(f"./tendon/spatial[@name='{original_name}']")
            template = tendons.get(muscle + "_tendon")
            if target is None or template is None:
                raise ValueError("source hand transmission unavailable: " + muscle)
            source_actuator = raw.find(f"./actuator/*[@name='{muscle}']")
            target_actuator = root.find(f"./actuator/*[@name='{muscle}_{side}']")
            if source_actuator is not None:
                target_actuator.set("lengthrange", source_actuator.get("lengthrange"))
            for element in list(target):
                target.remove(element)
            for part in template:
                new_part = copy.deepcopy(part)
                for kind in ("site", "geom", "sidesite"):
                    if kind not in part.attrib:
                        continue
                    name = part.get(kind)
                    identifier = "hand_detail_" + side + "_" + name
                    new_part.set(kind, identifier)
                    if identifier in copied:
                        continue
                    copied.add(identifier)
                    is_site = kind in ("site", "sidesite")
                    element = (raw_sites if is_site else raw_geoms)[name]
                    obj = model.site(name) if is_site else model.geom(name)
                    bid = int(obj.bodyid[0])
                    if bid in descendants:
                        parent = bodies[bid]
                        new = transformed(element, bid, identifier)
                    else:
                        body_name = model.body(bid).name
                        body_name = "proximal_row_r" if body_name == "proximal_row" else body_name
                        if side == "l":
                            body_name = body_name.removesuffix("_r") + "_l"
                        parent = root.find(f".//body[@name='{body_name}']")
                        if parent is None:
                            raise ValueError("source body correspondence missing: " + body_name)
                        new = copy.deepcopy(element)
                        new.set("name", identifier)
                        position = np.fromstring(new.get("pos", "0 0 0"), sep=" ")
                        new.set("pos", " ".join(map(str, reflection @ position)))
                        q = np.fromstring(new.get("quat", "1 0 0 0"), sep=" ")
                        if side == "l":
                            q[1:3] *= -1
                        new.set("quat", " ".join(map(str, q)))
                    if not is_site:
                        new.set("contype", "0")
                        new.set("conaffinity", "0")
                        new.set("mass", "0")
                    parent.append(new)
                target.append(new_part)
            rerouted.append(original_name)
        if articulated:
            add_patches(mj, target_hand, model, data, hand, bodies, side, reflection)
        for i, position in enumerate(centers):
            ET.SubElement(target_hand, "geom", name=f"palm_{side}" if i == 0 else f"palm_{side}_{i}",
                          type="sphere", size="0.009", pos=" ".join(map(str, reflection @ position)),
                          mass="0", contype="2", conaffinity="4", friction="1.3 .005 .0001", solref=".01 1", rgba=".05 .65 .6 .5")
    return mj.MjSpec.from_string(ET.tostring(root, encoding="unicode")), {
        "support": support, "source": "pinned MS-Human-700-Manipulation.xml right articulated hand and native mirrored left meshes",
        "source_finger_joint_posture_rad": posture, "finger_dynamics": ("native digit hinges and 4/5 CMC coupling; passive patch loads are proxy mechanics" if articulated
                            else "rigid posture; no independent finger integration or grip-force estimation"),
        "left_posture": "sagittal reflection of source right posture; native source mirrored meshes",
        "bone_geometries": added_bones, "rerouted_tendons": rerouted,
        "lengthrange": "native manipulation-hand actuator length ranges where supplied; unchanged source maximum forces",
        **({"palm_contact_patch_count_per_hand": len(PALM_PATCHES),
            "digit_contact_capsule_count_per_hand": len(FINGER_CAPSULES),
            "palm_patch_radii_m": {region: radius for region, _, radius in PALM_PATCHES.values()}}
           if articulated else {"support_points_per_hand": len(centers), "mechanical_pad_radius_m": .009}),
        "wrist_ligaments": "unavailable: no discrete ligament elements in the pinned model",
        "tendon_mechanics": "native muscle-tendon transmission paths; no independently deformable tendon tissue",
        "retained_hand_inertia": ("neutral total mass, COM and inertia preserved; donor child inertials allocated at one quarter of the native values"
                                  if articulated else "primary source hand mass/inertia, no mass from added display meshes")}


def measure_knuckle_technique(model, data):
    """Geometric grip/elbow measurements; engineering targets, not clinical angles."""
    shoulders = {s: data.xanchor[model.joint("shoulder_elv_" + s).id] for s in "rl"}
    lateral = shoulders["l"] - shoulders["r"]
    lateral /= np.linalg.norm(lateral)
    cranial = (shoulders["r"] + shoulders["l"]) / 2 - data.xpos[model.body("pelvis").id]
    cranial -= lateral * (cranial @ lateral)
    cranial /= np.linalg.norm(cranial)
    forward = cranial.copy()
    forward[2] = 0
    forward /= np.linalg.norm(forward)
    values = {}
    for s in "rl":
        rotation = data.xmat[model.body("hand_" + s).id].reshape(3, 3)
        inward = lateral if s == "r" else -lateral
        palm = rotation[:, 2] * (-1 if s == "r" else 1)
        upper_arm = data.xanchor[model.joint("elbow_flexion_" + s).id] - shoulders[s]
        values[f"hand_{s}_palm_inward_cosine"] = float(palm @ inward)
        values[f"hand_{s}_radial_forward_cosine"] = float(rotation[:, 0] @ forward)
        values[f"elbow_{s}_flare_rad"] = float(np.arctan2(abs(upper_arm @ lateral), max(0, -upper_arm @ cranial)))
        values[f"shoulder_{s}_above_elbow_m"] = float(-upper_arm[2])
    return values


def measure_palm_technique(model, data):
    """Palm supports relative to native shoulder/chest landmarks projected onto the floor."""
    values = measure_knuckle_technique(model, data)
    head = data.geom_xpos[model.geom("skull").id]
    shoulders = [data.xanchor[model.joint("shoulder_elv_" + s).id] for s in "rl"]
    forward = (np.mean(shoulders, axis=0) - data.xpos[model.body("pelvis").id])[:2]
    forward /= np.linalg.norm(forward)
    sternum = model.geom("Sternum").id
    mesh = model.geom_dataid[sternum]
    vertices = model.mesh_vert[model.mesh_vertadr[mesh]:model.mesh_vertadr[mesh] + model.mesh_vertnum[mesh]]
    chest = vertices @ data.geom_xmat[sternum].reshape(3, 3).T + data.geom_xpos[sternum]
    chest_caudal = float(np.min(chest[:, :2] @ forward))
    for side in "rl":
        rotation = data.xmat[model.body("hand_" + side).id].reshape(3, 3)
        hand = data.xpos[model.body("hand_" + side).id]
        shoulder = data.xanchor[model.joint("shoulder_elv_" + side).id]
        values[f"hand_{side}_fingers_forward_cosine"] = float(-rotation[0, 1])
        values[f"hand_{side}_palm_down_cosine"] = float(rotation[2, 2] * (1 if side == "r" else -1))
        values[f"hand_{side}_ahead_head_m"] = float(hand[0] - head[0])
        values[f"hand_{side}_ahead_shoulder_m"] = float(hand[0] - shoulder[0])
        pads = [g for g in range(model.ngeom) if model.geom(g).name.startswith("palm_" + side) and "_surface_" not in model.geom(g).name]
        palm = np.mean(data.geom_xpos[pads], axis=0)
        from_shoulder = float((palm - shoulder)[:2] @ forward)
        from_chest = float(palm[:2] @ forward - chest_caudal)
        values[f"palm_{side}_ahead_shoulder_m"] = from_shoulder
        values[f"palm_{side}_ahead_chest_caudal_m"] = from_chest
        values[f"palm_{side}_shoulder_chest_gap_m"] = max(0., from_shoulder, -from_chest)
    return values


def palm_placement_passes(rows):
    """Declared 5 cm comparison tolerance, not a measured human anatomical bound."""
    return bool(rows) and all(r[f"palm_{s}_shoulder_chest_gap_m"] <= PALM_PLACEMENT_TOLERANCE_M
                              for r in rows for s in "rl")


def wrist_shaft_extension(model, data, side):
    """Projected forearm-to-hand angle; a geometric proxy, not clinical calibration."""
    shaft = (data.xanchor[model.joint("flexion_" + side).id]
             - data.xanchor[model.joint("elbow_flexion_" + side).id])
    local = data.xmat[model.body("hand_" + side).id].reshape(3, 3).T @ shaft
    return float(np.arctan2(-local[2] * (1 if side == "r" else -1), -local[1]))


def measure_wrists(mj, model, data, support):
    """Actual floor wrenches and native generalized components, not ligament tension."""
    floor = model.geom("floor").id
    rows, details = {}, []
    for side in "rl":
        body = model.body("hand_" + side).id
        joint = model.joint("flexion_" + side).id
        origin = data.xanchor[joint].copy()
        force, moment = np.zeros(3), np.zeros(3)
        contacts = []
        for i in range(data.ncon):
            c = data.contact[i]
            if floor not in c.geom:
                continue
            other = int(c.geom[1] if c.geom[0] == floor else c.geom[0])
            if not model.geom(other).name.startswith("palm_" + side):
                continue
            local = np.zeros(6)
            mj.mj_contactForce(model, data, i, local)
            sign = 1 if c.geom[0] == floor else -1
            f, torque = sign * c.frame.reshape(3, 3).T @ local[:3], sign * c.frame.reshape(3, 3).T @ local[3:]
            force += f
            moment += np.cross(c.pos - origin, f) + torque
            contacts.append({"geom": model.geom(other).name, "position_m": c.pos.tolist(),
                             "force_world_N": f.tolist(), "normal_force_N": float(local[0]), "gap_m": float(c.dist)})
        if mj.mj_name2id(model, mj.mjtObj.mjOBJ_EQUALITY, "ground_palm_r") >= 0:
            from .supports import fixed_reactions
            for reaction in fixed_reactions(mj, model, data):
                if not reaction["geom"].startswith("palm_" + side):
                    continue
                f = np.array(reaction["force_world_N"])
                force += f
                moment += np.cross(np.array(reaction["position_m"]) - origin, f)
                contacts.append({**reaction, "gap_m": reaction["position_m"][2]})
        local_normal = [0, 0, -1 if side == "r" else 1] if support == "palms" else [0, -1, 0]
        normal = data.xmat[body].reshape(3, 3) @ local_normal
        for axis, f, torque in zip("xyz", force, moment, strict=True):
            rows[f"hand_{side}_force_{axis}_N"] = float(f)
            rows[f"hand_{side}_ground_moment_{axis}_Nm"] = float(torque)
        rows[f"hand_{side}_support_tilt_rad"] = float(np.arccos(np.clip(-normal[2], -1, 1)))
        rows[f"hand_{side}_shaft_extension_rad"] = wrist_shaft_extension(model, data, side)
        rows[f"hand_{side}_bearing_points"] = sum(c["normal_force_N"] > 1 for c in contacts)
        for name in ("flexion", "deviation", "pro_sup"):
            j = model.joint(name + "_" + side).id
            dof = int(model.jnt_dofadr[j])
            rows[f"{name}_{side}_rad"] = float(data.qpos[model.jnt_qposadr[j]])
            rows[f"{name}_{side}_actuator_Nm"] = float(data.qfrc_actuator[dof])
            rows[f"{name}_{side}_passive_Nm"] = float(data.qfrc_passive[dof])
            rows[f"{name}_{side}_constraint_Nm"] = float(data.qfrc_constraint[dof])
        details.append({"side": side, "time_s": float(data.time), "wrist_origin_m": origin.tolist(),
                        "force_world_N": force.tolist(), "ground_moment_about_wrist_Nm": moment.tolist(),
                        "support_normal_world": normal.tolist(), "contacts": contacts,
                        "ligament_forces": None, "ligament_status": "not_modeled"})
    return rows, details
