"""Two-bone attachment of a sourced surface. The rig has no tissue mechanics."""

import numpy as np

from .atlas import atlas_lock, verify_asset

BONE_RMSE_LIMIT_M = .018
LANDMARK_LIMIT_M = .035

BONES = (
    ("FJ3362.obj", "clavicle", "clavicle_r", "PECM1_r-P4"),
    ("FJ3368.obj", "humerus", "humerus_r", "PECM1_r-P1"),
)


def surface(path, asset):
    verify_asset(path, asset)
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([float(x) for x in parts[1:]])
        elif parts[0] == "f":
            faces.append([int(x.split("/")[0]) - 1 for x in parts[1:]])
    vertices, faces = np.asarray(vertices), np.asarray(faces, dtype=int)
    if (not 3 <= len(vertices) <= 10000 or not 1 <= len(faces) <= 20000
            or vertices.shape != (len(vertices), 3) or faces.shape != (len(faces), 3)
            or not np.isfinite(vertices).all() or faces.min() < 0 or faces.max() >= len(vertices)
            or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)):
        raise ValueError("invalid atlas mesh topology or coordinates")
    triangles = vertices[faces]
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1)
    if np.any(area < 1e-9) or not 50 <= np.ptp(vertices, axis=0).max() <= 400:
        raise ValueError("degenerate atlas triangle or incompatible source millimetres")
    return vertices, faces


def nearest(points, target):
    indices, distances = [], []
    for batch in np.array_split(points, max(1, (len(points) + 127) // 128)):
        squared = np.sum((batch[:, None, :] - target[None, :, :]) ** 2, axis=2)
        index = np.argmin(squared, axis=1)
        indices.extend(index)
        distances.extend(np.sqrt(squared[np.arange(len(index)), index]))
    return np.asarray(indices), np.asarray(distances)


def rigid_fit(source, target):
    """Proper rigid fit of explicit paired landmarks in metres."""
    if (source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3
            or not np.isfinite(source).all() or not np.isfinite(target).all()):
        raise ValueError("invalid 3D landmark pairs")
    x, y = source - source.mean(0), target - target.mean(0)
    if min(np.linalg.matrix_rank(x), np.linalg.matrix_rank(y)) < 2:
        raise ValueError("degenerate 3D landmark pairs")
    u, _, vh = np.linalg.svd(x.T @ y)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(u @ vh)
    rotation = u @ correction @ vh
    return rotation, target.mean(0) - source.mean(0) @ rotation


def native_bone(model, data, geom_name):
    geom = model.geom(geom_name)
    mid = int(geom.dataid[0])
    start, count = int(model.mesh_vertadr[mid]), int(model.mesh_vertnum[mid])
    vertices = model.mesh_vert[start:start + count]
    return vertices @ data.geom_xmat[geom.id].reshape(3, 3).T + data.geom_xpos[geom.id]


def register(model, neutral, pinned_model, folder):
    lock = atlas_lock()
    if (pinned_model["revision"], pinned_model["asset_sha256"]) != (lock["model_revision"], lock["model_asset_sha256"]):
        raise ValueError("atlas registration model pin mismatch")
    basis = np.asarray(lock["source_coordinates"]["world_basis"])
    if (lock["source_coordinates"]["unit"] != "mm" or basis.shape != (3, 3)
            or not np.array_equal(basis @ basis.T, np.eye(3)) or np.linalg.det(basis) != 1):
        raise ValueError("atlas coordinate basis or unit mismatch")
    vertices, faces = surface(folder / "FJ1447.obj", lock["files"]["FJ1447.obj"])
    vertices = vertices @ basis.T / 1000
    local_vertices, contact_distances, reports = [], [], []
    for name, geom, body, site in BONES:
        raw, _ = surface(folder / name, lock["files"][name])
        atlas_bone = raw @ basis.T / 1000
        native = native_bone(model, neutral, geom)
        # Use long-axis extrema and the pinned anatomically oriented basis to
        # initialize vertex registration without a reflection or independent scales.
        dominant = int(np.argmax(np.ptp(atlas_bone, axis=0)))
        low, high = np.argmin(atlas_bone[:, dominant]), np.argmax(atlas_bone[:, dominant])
        native_low, native_high = np.argmin(native[:, dominant]), np.argmax(native[:, dominant])
        r = np.eye(3)
        t = (native[native_low] + native[native_high] - atlas_bone[low] - atlas_bone[high]) / 2
        for _ in range(35):
            matched, distances = nearest(native, atlas_bone @ r + t)
            keep = distances <= np.quantile(distances, .90)
            r, t = rigid_fit(atlas_bone[matched[keep]], native[keep])
        aligned = atlas_bone @ r + t
        _, distances = nearest(native, aligned)
        rmse = float(np.sqrt(np.mean(distances ** 2)))
        _, reverse = nearest(aligned, native)
        if rmse > BONE_RMSE_LIMIT_M or np.linalg.det(r) < .999999 or np.trace(r) < 1:
            raise ValueError(f"atlas bone registration outside engineering bounds for {body}: {rmse:.5f} m")
        transformed = vertices @ r + t
        bid, sid = model.body(body).id, model.site(site).id
        if int(model.site_bodyid[sid]) != bid:
            raise ValueError("source attachment site belongs to a different body")
        local_vertices.append((transformed - neutral.xpos[bid]) @ neutral.xmat[bid].reshape(3, 3))
        _, proximity = nearest(vertices, atlas_bone)
        contact_distances.append(proximity)
        expected = neutral.site_xpos[sid]
        attachment_region = proximity <= np.quantile(proximity, .05)
        matched, _ = nearest(native, aligned)
        landmarks = []
        for label, index in (("long_axis_low", native_low), ("long_axis_high", native_high),
                             ("nearest_native_attachment", int(np.argmin(np.linalg.norm(native - expected, axis=1))))):
            atlas_index = int(matched[index])
            landmarks.append({"name": label, "native_vertex": int(index), "atlas_vertex": atlas_index,
                              "residual_m": float(np.linalg.norm(native[index] - aligned[atlas_index]))})
        attachment_error = float(np.linalg.norm(transformed[attachment_region] - expected, axis=1).min())
        if max(attachment_error, *(entry["residual_m"] for entry in landmarks)) > LANDMARK_LIMIT_M:
            raise ValueError(f"atlas landmark or attachment mismatch for {body}")
        reports.append({"bone": body, "atlas_object": name, "source_rotation_row_vectors": r.tolist(),
                        "source_translation_m": t.tolist(), "rotation_determinant": float(np.linalg.det(r)),
                        "native_to_atlas_vertex_rmse_m": rmse, "rmse_limit_m": BONE_RMSE_LIMIT_M,
                        "landmark_limit_m": LANDMARK_LIMIT_M,
                        "atlas_to_native_vertex_rmse_m": float(np.sqrt(np.mean(reverse ** 2))),
                        "landmark_proxies": landmarks, "model_attachment_site": site,
                        "attachment_near_bone_vertices": int(attachment_region.sum()),
                        "attachment_gap_at_rest_m": attachment_error})
    clavicle, humerus = contact_distances
    weight = clavicle / np.maximum(clavicle + humerus, 1e-12)
    weight = np.clip((weight - .15) / .70, 0, 1)
    # Welding identical coordinates here is diagnostic only. Blender retains the source topology.
    _, welded = np.unique(vertices, axis=0, return_inverse=True)
    tri = welded[faces]
    edges = np.sort(np.vstack((tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]])), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return faces, local_vertices, weight[:, None], {
        "status": "illustrative",
        "source": lock,
        "anatomical_id": lock["files"]["FJ1447.obj"]["anatomical_id"],
        "method": "Rigid nearest-vertex bone fits at native qpos0, followed by fixed distance-weighted two-bone skinning",
        "bone_fits": reports,
        "vertices": len(vertices),
        "triangles": len(faces),
        "source_topology": {"boundary_edges_after_exact_weld": int(np.count_nonzero(counts == 1)),
                            "nonmanifold_edges_after_exact_weld": int(np.count_nonzero(counts > 2))},
        "activation_mapping": "unavailable; fixed anatomical display colour",
        "display_material": {
            "name": "Atlas muscle · procedural fibres",
            "linear_rgb": [.44, .092, .056],
            "linear_rgb_role": "highlight palette entry",
            "orientation": "dominant geometry axis for display",
            "interpretation": "fixed procedural shading; no measured fibre field or activation",
        },
        "limitations": [
            "Nearest vertices and extrema are geometric proxies. Landmark homology and attachment footprints lack specialist review.",
            "The generic donor and model differ in anthropometry. Similarity of bone surfaces does not establish muscle registration accuracy.",
            "Surface trajectories are visual skinning. Fiber orientation, material properties, tissue mechanics and other atlas structures are unavailable.",
        ],
    }


def skin(model, data, registration):
    faces, local, weight, _ = registration
    anchors = []
    for vertices, (_, _, body, _) in zip(local, BONES, strict=True):
        bid = model.body(body).id
        anchors.append(vertices @ data.xmat[bid].reshape(3, 3).T + data.xpos[bid])
    current = anchors[0] + weight * (anchors[1] - anchors[0])
    triangles = current[faces]
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1) / 2
    if not np.isfinite(current).all() or np.any(area <= 1e-12) or current[:, 2].min() < -.005:
        raise ValueError("invalid skinned mesh triangles or below-floor surface")
    gaps = {}
    for part, mask in zip(BONES, (weight[:, 0] <= .05, weight[:, 0] >= .95), strict=True):
        if not np.any(mask):
            raise ValueError("atlas mesh has no near-rigid attachment region")
        _, _, body, site = part
        gaps[body] = float(np.linalg.norm(current[mask] - data.site_xpos[model.site(site).id], axis=1).min())
    return current, {"minimum_z_m": float(current[:, 2].min()), "minimum_triangle_area_m2": float(area.min()),
                     "maximum_triangle_area_m2": float(area.max()), "site_to_near_rigid_surface_m": gaps}
