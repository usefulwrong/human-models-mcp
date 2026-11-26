"""Contact debug meshes shared by the browser and Blender through MotionScene."""


import mujoco as mj
import numpy as np

from glb import B4, BASIS


def floor_events(mj_model, data):
    floor = mj_model.geom("floor").id
    events = []
    load = np.empty(6)
    for i in range(data.ncon):
        c = data.contact[i]
        if floor not in c.geom:
            continue
        mj.mj_contactForce(mj_model, data, i, load)
        if load[0] > 1e-6:
            # MuJoCo contact frame rows are world axes; geom[1] receives the positive normal.
            normal = c.frame[:3] * (1 if c.geom[0] == floor else -1)
            events.append((c.pos.copy(), normal.copy()))
    return events


def markers(clip, events, label, material, *, radius):
    # Small tapered glyphs give a visible base point and the measured vector direction.
    points = np.array([[0, 0, 0], [1, .12, 0], [0, .12, 1],
                       [-1, .12, 0], [0, .12, -1], [0, 1, 0]])
    faces = [[0, i, i % 4 + 1] for i in range(1, 5)] + [[5, i % 4 + 1, i] for i in range(1, 5)]
    for marker in range(max(map(len, events), default=0)):
        node, _ = clip.mesh(f"{label} {marker + 1}", "OVERLAYS", points, np.array(faces), material)
        positions = np.zeros((len(events), 3))
        scales = np.zeros_like(positions)
        rotations = np.tile([0., 0., 0., 1.], (len(events), 1))
        for i, frame in enumerate(events):
            if marker < len(frame):
                pos, vector = frame[marker]
                positions[i] = BASIS @ pos
                length = np.linalg.norm(vector)
                quat = np.empty(4)
                mj.mju_quatZ2Vec(quat, BASIS @ vector / length)
                # mju_quatZ2Vec maps local Z, while the glTF glyph extends along local Y.
                q = np.empty(4)
                mj.mju_mulQuat(q, quat, np.array([2**-.5, 2**-.5, 0, 0]))
                rotations[i] = q[[1, 2, 3, 0]]
                scales[i] = [radius, length, radius]
        for path, values, kind in (("translation", positions, "VEC3"), ("scale", scales, "VEC3"),
                                   ("rotation", rotations, "VEC4")):
            clip.channel(node, path, values, kind)
            clip.doc["animations"][0]["samplers"][-1]["interpolation"] = "STEP"


def capsule_mesh(radius, half_length):
    theta = np.linspace(0, np.pi / 2, 5)
    angles = np.arange(16) * np.pi / 8
    rings = np.stack((radius * np.sin(theta), half_length + radius * np.cos(theta)), axis=1)
    rings = np.vstack((rings, rings[::-1] * [1, -1]))
    points = np.array([[r * np.cos(a), r * np.sin(a), z] for r, z in rings for a in angles])
    faces = np.array([face for row in range(len(rings) - 1) for col in range(16)
                      for a, b in [(16 * row + col, 16 * row + (col + 1) % 16)]
                      for face in ((a, a + 16, b), (b, a + 16, b + 16))])
    return points, faces


def experimental_overlays(clip, model, poses, proxies, manifest, surface_frames, events, sphere, sphere_faces):
    envelope = clip.material("Physical proxy envelope", (.04, .39, .45))
    material = clip.doc["materials"][envelope]
    material["pbrMetallicRoughness"]["baseColorFactor"][3] = .27
    material["alphaMode"] = "BLEND"
    for g in proxies:
        name = model.geom(g).name
        if model.geom_type[g] == mj.mjtGeom.mjGEOM_SPHERE:
            points, faces = sphere * model.geom_size[g, 0], sphere_faces
        elif model.geom_type[g] == mj.mjtGeom.mjGEOM_CAPSULE:
            points, faces = capsule_mesh(*model.geom_size[g, :2])
        else:
            m = model.geom_dataid[g]
            start = model.mesh_vertadr[m]
            points = model.mesh_vert[start:start + model.mesh_vertnum[m]].astype(float)
            # Pinned MuJoCo 3.17.0 mesh graph stores global face vertices after the adjacency arrays.
            graph = model.mesh_graphadr[m]
            if graph < 0:
                raise ValueError("collider lacks the compiled convex hull")
            nv, nf = model.mesh_graph[graph:graph + 2]
            start = graph + 2 + 3 * nv + 3 * nf
            faces = model.mesh_graph[start:start + 3 * nf].reshape(-1, 3)
        node, _ = clip.mesh(name, "OVERLAYS", points @ BASIS.T, faces, envelope, geom=g)
        clip.transforms(node, B4 @ poses[g] @ B4.T)

    normal = np.asarray(manifest["floor"]["normal"])
    markers(clip, [[(pos, axis * .028) for pos, axis in frame] for frame in events],
            "Native floor normal", clip.material("Native floor contact", (.03, .82, .84)), radius=.002)
    clipping = [[(pos, normal * dist) for dist, pos in frame["surfaces"].values() if dist < -.00002]
                for frame in surface_frames]
    markers(clip, [[(pos + vector, -vector) for pos, vector in frame] for frame in clipping],
            "Signed surface depth", clip.material("Surface below plane", (.9, .06, .18)), radius=.0018)
