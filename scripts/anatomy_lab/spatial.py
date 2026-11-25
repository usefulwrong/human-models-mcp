"""Bounded source OBJ triangle queries in the reviewed regional source frame."""

import numpy as np

from anatomy_lab import FRAME, clinical
from human_models_mcp.atlas import atlas_lock
from human_models_mcp.atlas_registration import surface
from human_models_mcp.results import error


def triangles(registry, mesh_id):
    # The existing regional lock documents ordering, axes, units and geometry.
    # Other parts require a frame and topology review before numerical queries.
    lock = atlas_lock()
    filename = f"{mesh_id}.obj"
    pinned = lock["files"].get(filename)
    if not pinned:
        raise LookupError("mesh is outside the reviewed spatial-query region")
    asset, _ = registry.mesh(mesh_id)
    if asset["sha256"] != pinned["sha256"]:
        raise ValueError("source mesh differs from the reviewed frame pin")
    vertices, faces = surface(registry.mesh_dir / filename, pinned)
    return vertices[faces], asset["sha256"]


def nearest(points, target):
    a, b, c = np.moveaxis(points, 1, 0)
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    normal_squared = np.einsum("ij,ij->i", normal, normal)
    projection = target - (np.einsum("ij,ij->i", target - a, normal) / normal_squared)[:, None] * normal
    edges = ((a, b), (b, c), (c, a))
    inside = np.ones(len(points), dtype=bool)
    candidates = [projection]
    for start, end in edges:
        edge = end - start
        signed = np.einsum("ij,ij->i", np.cross(edge, projection - start), normal)
        inside &= signed >= -1e-12
        fraction = np.einsum("ij,ij->i", target - start, edge) / np.einsum("ij,ij->i", edge, edge)
        candidates.append(start + np.clip(fraction, 0, 1)[:, None] * edge)
    candidates = np.stack(candidates)
    squared = np.sum((candidates - target) ** 2, axis=-1)
    squared[0, ~inside] = np.inf
    candidate, face = np.unravel_index(np.argmin(squared), squared.shape)
    return {"point_mm": candidates[candidate, face].tolist(), "distance_mm": float(np.sqrt(squared[candidate, face])),
            "triangle_index": int(face)}


def raycast(points, origin, direction):
    norm = np.linalg.norm(direction)
    if norm < 1e-12:
        raise ValueError("ray direction must be nonzero")
    ray = direction / norm
    a, b, c = np.moveaxis(points, 1, 0)
    e1, e2 = b - a, c - a
    cross = np.cross(ray, e2)
    determinant = np.einsum("ij,ij->i", e1, cross)
    proper = np.abs(determinant) > 1e-12
    inv = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=proper)
    roots = origin - a
    u = np.einsum("ij,ij->i", roots, cross) * inv
    q = np.cross(roots, e1)
    v = (q @ ray) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hits = np.where(proper & (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10) & (t >= 0))[0]
    if not hits.size:
        return {"hit": False}
    face = int(hits[np.argmin(t[hits])])
    return {"hit": True, "triangle_index": face, "distance_mm": float(t[face]),
            "point_mm": (origin + t[face] * ray).tolist()}


def query(registry, request):
    if request.method == "clinical":
        return clinical()
    if request.frame != FRAME or not request.mesh:
        return error("unsupported", "spatial queries require one reviewed mesh in " + FRAME)
    for vec in (request.point, request.direction):
        if vec is not None and max(map(abs, vec)) > 1e6:
            return error("invalid_input", "coordinate exceeds the spatial-query budget")
    points, sha = triangles(registry, request.mesh)
    source = {request.mesh: sha}
    if request.method == "relative":
        if not request.other_mesh:
            return error("invalid_input", "relative requires two mesh IDs")
        other, other_sha = triangles(registry, request.other_mesh)
        source[request.other_mesh] = other_sha
        center = lambda p: (p.min(axis=(0, 1)) + p.max(axis=(0, 1))) / 2  # noqa: E731
        delta = center(points) - center(other)
        result = {"first_minus_second_mm": delta.tolist(),
                  "patient_left_direction": "positive_x", "posterior_direction": "positive_y",
                  "superior_direction": "positive_z"}
        method = "axis-aligned bounding-box center difference"
    elif request.point is None:
        return error("invalid_input", "point is required")
    elif request.method == "nearest":
        result = nearest(points, np.asarray(request.point))
        method = "closest point on source triangles, including edges"
    else:
        if request.direction is None or max(map(abs, request.direction)) < 1e-12:
            return error("invalid_input", "nonzero ray direction is required")
        result = raycast(points, np.asarray(request.point), np.asarray(request.direction))
        method = "first two-sided ray-triangle intersection"
    return {"status": "ok", "coordinate_frame": FRAME, "unit": "mm", "method": method, "source_sha256": source,
            "coordinate_frame_evidence": "v0.8 inferred source basis, reviewed regional pin",
            "evidence": "source_geometry", **result}
