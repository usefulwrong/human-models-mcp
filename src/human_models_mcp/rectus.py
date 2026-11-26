"""Pinned Z-Anatomy bilateral rectus surface and saved-site registration."""

import shutil
from pathlib import Path

import numpy as np

from .atlas import atlas_cache, atlas_lock, verify_asset
from .rendering import write_json

SIDES = ("r", "l")
ASSET = "rectus.npz"
SOURCE = {
    "name": "Z-Anatomy, adapted from BodyParts3D © DBCLS",
    "author": "Gauthier Kervyn; BodyParts3D by Kousaku Okubo and DBCLS",
    "url": "https://github.com/Z-Anatomy/Models-of-human-anatomy/tree/0a849e8acf7080f8da3251a926fbc160d2bc3f7a",
    "revision": "0a849e8acf7080f8da3251a926fbc160d2bc3f7a",
    "source_blend_sha256": "9f08a17ea0115fed80b2a73ecdf0a1bc2ab2f6956f37c593ce23d513ea35afcd",
    "license": "CC-BY-SA-4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "objects": ["Rectus abdominis muscle.r", "Rectus abdominis muscle.l"],
    "source_coordinates": "baked Z-Anatomy world transforms, metres, right-handed; +X left, +Z superior",
    "files": {ASSET: {"sha256": "01fc5dab901433422c766d8fbbb5beef16824f055a4eca6d1db27f33b13e61c4",
                      "bytes": 375769}},
}


def provision_rectus(accepted_license, source):
    if accepted_license != SOURCE["license"]:
        raise ValueError("explicit acceptance of " + SOURCE["license"] + " required")
    source = Path(source)
    asset = SOURCE["files"][ASSET]
    verify_asset(source, asset)
    cache = atlas_cache()
    cache.mkdir(exist_ok=True)
    if cache.is_symlink():
        raise ValueError("invalid atlas cache directory")
    target = cache / ASSET
    if not target.exists() and not target.is_symlink():
        with source.open("rb") as original, target.open("xb") as dest:
            shutil.copyfileobj(original, dest)
    verify_asset(target, asset)
    write_json(cache / "rectus_license.json", {"license": accepted_license, "sha256": asset["sha256"]})
    return SOURCE


def rectus_inputs():
    import json

    cache = atlas_cache()
    receipt = cache / "rectus_license.json"
    asset = SOURCE["files"][ASSET]
    if (cache.is_symlink() or receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 1024
            or json.loads(receipt.read_text(encoding="utf-8")) != {"license": SOURCE["license"], "sha256": asset["sha256"]}):
        raise ValueError("rectus license receipt missing or invalid; use provision-rectus")
    verify_asset(cache / ASSET, asset)
    return SOURCE


def segment_frame(lower, upper, left):
    axis = upper - lower
    length = np.linalg.norm(axis)
    if not np.isfinite(length) or not .2 < length < .65:
        raise ValueError("rectus landmark distance outside metre-scale bounds")
    up = axis / length
    lateral = left - up * (left @ up)
    norm = np.linalg.norm(lateral)
    if not np.isfinite(norm) or norm < .02:
        raise ValueError("rectus lateral and longitudinal landmarks are degenerate")
    lateral /= norm
    return np.column_stack((lateral, np.cross(up, lateral), up)), length


def register(path, pinned_model):
    lock = atlas_lock()
    if (pinned_model["revision"], pinned_model["asset_sha256"]) != (lock["model_revision"], lock["model_asset_sha256"]):
        raise ValueError("rectus registration model pin mismatch")
    verify_asset(path, SOURCE["files"][ASSET])
    meshes = {}
    with np.load(path, allow_pickle=False) as arrays:
        for side in SIDES:
            vertices = arrays[f"{side}_vertices"].astype(float)
            faces, tendon = arrays[f"{side}_faces"], arrays[f"{side}_tendon"]
            if (vertices.shape != (10304, 3) or not np.isfinite(vertices).all() or faces.shape != (20604, 3)
                    or faces.min() < 0 or faces.max() >= len(vertices)
                    or tendon.shape != (20604,) or not np.isin(tendon, (0, 1)).all() or tendon.sum() != 6611):
                raise ValueError("invalid pinned rectus topology, coordinates or tendon assignments")
            z = vertices[:, 2]
            lower, upper = z.min(), z.max()
            if not (.84 < lower < .86 and 1.24 < upper < 1.27):
                raise ValueError("rectus source axis or unit mismatch")
            lo = vertices[z < lower + .012].mean(axis=0)
            hi = vertices[z > upper - .012].mean(axis=0)
            basis, length = segment_frame(lo, hi, np.array([1., 0., 0.]))
            local = (vertices - lo) @ basis
            triangles = local[faces]
            if np.any(np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                               triangles[:, 2] - triangles[:, 0]), axis=1) <= 1e-12):
                raise ValueError("degenerate rectus mesh triangles")
            meshes[side] = (local, float(length), faces, tendon)
    return meshes


def skin(model, data, meshes):
    sites = {side: np.asarray([data.site_xpos[model.site(f"rect_abd_{side}-P{i}").id]
                              for i in (1, 4)]) for side in SIDES}
    left = sites["l"][1] - sites["r"][1]
    mid_lo, mid_hi = (sites["l"] + sites["r"]) / 2
    midsagittal, _ = segment_frame(mid_lo, mid_hi, left)
    surfaces, checks = {}, {}
    for side, (local, length, _, _) in meshes.items():
        lo, hi = sites[side]
        basis, distance = segment_frame(lo, hi, left)
        scale = float(distance / length)
        if not .73 <= scale <= 1.35:
            raise ValueError(f"rectus transfer beyond axial scale bound: {scale}")
        world = (local * [1, 1, scale]) @ basis.T + lo
        signed = ((world - mid_lo) @ midsagittal[:, 0]) * (1 if side == "l" else -1)
        residual = float(np.linalg.norm(lo + basis[:, 2] * (scale * length) - hi))
        if residual > 2e-6 or not np.isfinite(world).all() or np.median(signed) <= 0:
            raise ValueError("rectus centreline, scale or laterality mismatch")
        surfaces[side] = world
        checks[side] = {"axial_scale": scale, "anchor_error_m": residual,
                        "fraction_of_vertices_across_midline": float(np.mean(signed < 0)),
                        "minimum_surface_z_m": float(world[:, 2].min())}
    return surfaces, checks, {side: points.tolist() for side, points in sites.items()}
