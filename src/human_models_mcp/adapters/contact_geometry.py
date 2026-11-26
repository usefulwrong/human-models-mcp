"""Floor-only, massless collision geometry for the experimental palm push-up."""

import numpy as np

# The primary model uses bits 1, 2 and 4. Only the experimental floor accepts bit 8.
FLOOR_BIT = 8
SPHERE_RADIUS_M = .004
SPHERE_CLEARANCE_M = .001
SUPPORTS = ("palm_r", "palm_l", "toe_r", "toe_l")
GUARDS = frozenset(("skull", "jaw", "Sternum", "r_patella", "l_patella", "r_pelvis", "l_pelvis",
                    "humerus", "ulna", "radius", "humerus_mirror", "ulna_mirror", "radius_mirror"))


def mesh_vertices(model, g):
    mesh = model.geom_dataid[g]
    start = model.mesh_vertadr[mesh]
    return model.mesh_vert[start:start + model.mesh_vertnum[mesh]].astype(float)


def support_name(body):
    if body.startswith("hand_"):
        return "palm_" + body[-1]
    if body.startswith(("toes_", "calcn_")):
        return "toe_" + body[-1]
    return "guard"


def add_floor_geometry(mj, spec, model, reference, representation, friction, floor_margin_m):
    """Add proxies in source body coordinates and retain source geoms as display meshes."""
    from .articulated_palms import PROFILE

    data = mj.MjData(model)
    data.qpos[:] = reference
    mj.mj_kinematics(model, data)
    floor = spec.geom("floor")
    floor.contype, floor.conaffinity = 0, FLOOR_BIT
    floor.margin, floor.gap = floor_margin_m, 0
    floor.solref = [.004, 1]
    floor.solimp[:2] = [.95, .99]
    for g in spec.geoms:
        if g.contype == FLOOR_BIT:
            g.friction[0] = friction
            # Floor and patch priorities let native toe and guard settings stay independent.
            g.priority = 1
        elif g.name.startswith(("palm_", "toe_")):
            g.contype, g.conaffinity, g.rgba[3] = 0, 0, 0

    for g in range(model.ngeom):
        name = model.geom(g).name
        body_id = model.geom_bodyid[g]
        body = model.body(body_id).name
        support = support_name(body)
        if model.geom_type[g] != mj.mjtGeom.mjGEOM_MESH or model.geom_rgba[g, 3] <= 0:
            continue
        if representation == PROFILE and (support.startswith("palm_") or name.startswith("hand_detail_")):
            continue
        if support == "guard" and name not in GUARDS:
            continue
        source = spec.geom(name)
        settings = dict(name=f"{support}_surface_{name}", mass=0, contype=FLOOR_BIT, conaffinity=0,
                        rgba=[0, 0, 0, 0], group=5, condim=3, friction=[friction, .005, .0001],
                        solref=[.004, 1], solimp=[.95, .99, .001, .5, 2], margin=0, gap=0)
        if representation == "surface_spheres_v1" and support != "guard":
            # Fit the sphere's bottom to the floor-facing extreme at the shared reference pose.
            rotation = data.geom_xmat[g].reshape(3, 3)
            world = mesh_vertices(model, g) @ rotation.T + data.geom_xpos[g]
            point = world[world[:, 2].argmin()] + [0, 0, SPHERE_RADIUS_M - SPHERE_CLEARANCE_M]
            local = data.xmat[body_id].reshape(3, 3).T @ (point - data.xpos[body_id])
            spec.body(body).add_geom(type=mj.mjtGeom.mjGEOM_SPHERE, size=[SPHERE_RADIUS_M, 0, 0],
                                     pos=local, **settings)
        else:
            spec.body(body).add_geom(type=mj.mjtGeom.mjGEOM_MESH, meshname=source.meshname,
                                     pos=source.pos.copy(), quat=source.quat.copy(), **settings)


def contact_manifest(mj, model, data, representation):
    from .articulated_palms import PROFILE, region

    floor = model.geom("floor").id
    proxies = {}
    surfaces = {}
    for g in range(model.ngeom):
        name = model.geom(g).name
        if model.geom_contype[g] != FLOOR_BIT:
            continue
        source = name.split("_surface_", 1)[1]
        body = model.body(model.geom_bodyid[g]).name
        surfaces[source] = {"geom_id": model.geom(source).id, "collision_geoms": [name], "body": body,
                            "joints": [model.joint(j).name for j in range(model.njnt)
                                       if model.jnt_bodyid[j] == model.geom_bodyid[g]]}
        proxies[name] = {"geom_id": g, "body": body, "type": mj.mjtGeom(int(model.geom_type[g])).name,
                         "contype": FLOOR_BIT, "conaffinity": 0, "condim": int(model.geom_condim[g]),
                         "pos_m": model.geom_pos[g].tolist(), "quat_wxyz": model.geom_quat[g].tolist(),
                         "size_m": model.geom_size[g].tolist(), "friction": model.geom_friction[g].tolist(),
                         "solref": model.geom_solref[g].tolist(), "solimp": model.geom_solimp[g].tolist(),
                         "margin_m": float(model.geom_margin[g]), "gap_m": float(model.geom_gap[g])}
        if representation == PROFILE and name.startswith("palm_"):
            proxies[name]["support_region"] = region(name)
    return {"schema_version": "1.0.0", "profile": representation, "world": "right-handed Z-up, metres",
            "floor": {"geom_id": floor, "position_m": data.geom_xpos[floor].tolist(),
                      "normal": data.geom_xmat[floor].reshape(3, 3)[:, 2].tolist(),
                      "contype": int(model.geom_contype[floor]), "conaffinity": int(model.geom_conaffinity[floor]),
                      "margin_m": float(model.geom_margin[floor]), "gap_m": float(model.geom_gap[floor])},
            "visible_surfaces": surfaces, "collision_geoms": proxies,
            "states": "trajectory.npz", "state_samples": "series.csv", "events": "contacts.json",
            "provenance": "pinned MS-Human-700 native bone meshes, attached to their native rigid bodies",
            "limitations": [("Articulated rigid finger links and compliant contact patches" if representation == PROFILE
                             else "Rigid source fingers"), "Selected skeletal floor coverage", "No modeled skin or pressure",
                            "A surface mapping does not imply a force-bearing event"]}


def initial_floor_gap(mj, model, data):
    gap = np.inf
    for g in np.flatnonzero(model.geom_contype == FLOOR_BIT):
        kind = model.geom_type[g]
        if kind == mj.mjtGeom.mjGEOM_SPHERE or kind == mj.mjtGeom.mjGEOM_CAPSULE:
            edge = data.geom_xpos[g, 2] - model.geom_size[g, 0]
            if kind == mj.mjtGeom.mjGEOM_CAPSULE:
                edge -= model.geom_size[g, 1] * abs(data.geom_xmat[g, 8])
        else:
            edge = data.geom_xpos[g, 2] + (mesh_vertices(model, g) @ data.geom_xmat[g, 6:9]).min()
        gap = min(gap, edge)
    return float(gap - data.geom_xpos[model.geom("floor").id, 2])


class FloorHistory:
    """Measure native floor wrenches at the integration clock."""

    def __init__(self, mj, model, floor):
        self.mj, self.model, self.floor = mj, model, floor
        self.rows = []
        self.max_cone_error = 0.
        self.guard_loaded = False
        self.impulse = {}
        self.dt = float(model.opt.timestep)
        self.wrench = np.zeros(6)

    def record(self, data, step):
        events = []
        for i in range(data.ncon):
            c = data.contact[i]
            if self.floor not in c.geom:
                continue
            side = int(c.geom[0] == self.floor)
            g = int(c.geom[side])
            self.mj.mj_contactForce(self.model, data, i, self.wrench)
            w = self.wrench
            if c.efc_address >= 0:
                self.max_cone_error = max(self.max_cone_error, -w[0],
                                          abs(w[1]) / c.friction[0] + abs(w[2]) / c.friction[1] - w[0])
            self.guard_loaded |= bool(w[0] > 1 and self.model.geom(g).name.startswith("guard_"))
            sign = 1 if side else -1
            force = sign * c.frame.reshape(3, 3).T @ w[:3]
            if step:
                self.impulse[g] = self.impulse.get(g, np.zeros(3)) + force * self.dt
            events.append([g, float(c.dist), c.pos.tolist(), (sign*c.frame[:3]).tolist(), w.tolist(), force.tolist()])
        self.rows.append([float(data.time), float(data.qfrc_applied @ data.qvel), events])

    def report(self):
        return {"schema_version": "1.0.0", "timestep_s": self.dt, "step_fields": ["time_s", "external_power_W", "events"],
                "event_fields": ["geom_id", "gap_m", "position_m", "normal_toward_body", "wrench_contact", "force_world_N"],
                "impulse_definition": "Right endpoint sum of native world force times dt",
                "impulse_world_Ns": {str(g): f.tolist() for g, f in self.impulse.items()},
                "max_cone_error_N": self.max_cone_error, "step_count": len(self.rows)}


def surface_samples(model, data, surfaces, vertices):
    floor = model.geom("floor").id
    origin = data.geom_xpos[floor]
    normal = data.geom_xmat[floor].reshape(3, 3)[:, 2]
    values = {}
    for name, record in surfaces.items():
        g = record["geom_id"]
        rotation = data.geom_xmat[g].reshape(3, 3)
        local = vertices[name]
        distance = local @ (rotation.T @ normal) + (data.geom_xpos[g] - origin) @ normal
        index = distance.argmin()
        values[name] = [float(distance[index]), (rotation @ local[index] + data.geom_xpos[g]).tolist()]
    return values
