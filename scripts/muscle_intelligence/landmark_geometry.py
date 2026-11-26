"""Mesh receipts and triangle-anchor validation for the shoulder pilot."""

from pathlib import Path

import numpy as np

TOLERANCE_MM = 0.05
MAX_GEOMETRY = 4 << 20


def surface(vertices, faces, unit_mm):
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=int)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or not 3 <= len(vertices) <= 60000
            or faces.ndim != 2 or faces.shape[1] != 3 or not 1 <= len(faces) <= 120000
            or not np.isfinite(vertices).all() or faces.min() < 0 or faces.max() >= len(vertices)
            or not 30 <= np.ptp(vertices, axis=0).max() * unit_mm <= 600
            or np.linalg.matrix_rank(vertices - vertices.mean(0)) < 3):
        raise ValueError("unsupported, degenerate or incorrectly scaled bone mesh")
    return {"vertices": vertices.tolist(), "triangles": faces.tolist()}


def obj(path: Path):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            vertices.append([float(value) for value in fields[1:4]])
        elif fields[0] == "f":
            indices = [int(value.split("/")[0]) for value in fields[1:]]
            if len(indices) != 3 or any(i <= 0 for i in indices):
                raise ValueError("pilot OBJ requires positive, triangular faces")
            faces.append([i - 1 for i in indices])
    return surface(vertices, faces, 1)


def native(model, name):
    mesh = int(model.geom(name).dataid[0])
    v, f = int(model.mesh_vertadr[mesh]), int(model.mesh_faceadr[mesh])
    # Compiled mesh vertices already include MuJoCo's mesh preprocessing.
    return surface(model.mesh_vert[v:v + model.mesh_vertnum[mesh]],
                   model.mesh_face[f:f + model.mesh_facenum[mesh]], 1000)


def check_anchor(mesh, point, anchor, mm_per_unit):
    if not 0 <= anchor.face < len(mesh["triangles"]):
        raise ValueError("point references a triangle outside the pinned mesh")
    triangle = np.asarray([mesh["vertices"][i] for i in mesh["triangles"][anchor.face]]) * mm_per_unit
    weights = np.asarray(anchor.weights)
    if (not np.isclose(weights.sum(), 1, rtol=0, atol=1e-6)
            or np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])) < 1e-8):
        raise ValueError("invalid barycentric weights or degenerate triangle")
    if np.linalg.norm(weights @ triangle - np.asarray(point) * mm_per_unit) > TOLERANCE_MM:
        raise ValueError("point is outside 0.05 mm of its pinned triangle anchor")


def validate_transform(transform):
    matrix = np.asarray(transform, dtype=float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.array_equal(matrix[3], [0, 0, 0, 1])):
        raise ValueError("invalid source-to-geom affine frame")
    rotation = matrix[:3, :3] * 1000
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-7) or not np.isclose(
            np.linalg.det(rotation), 1, atol=1e-7):
        raise ValueError("source-to-geom frame has unexpected scale or reflection")
