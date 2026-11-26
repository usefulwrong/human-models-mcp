"""Neutral wrist moment arms compared with published cadaver means; no fitting."""

import csv
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from ..registry import home, Validation
from .mujoco import load, moment_entry, render

REFERENCE_HASHES = {"article.xml": "babc83e6fb84423a807b980f2fed423ea0bb924310e707221c66350f5b2fa483",
                    "reference.csv": "9089e6a96b3c3090af3826aab141a60fdba8925f117349e05440af50089902cf"}


def reference():
    folder = home() / "benchmarks/nichols2016_wrist"
    for name, expected in REFERENCE_HASHES.items():
        if (folder / name).is_symlink() or hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError("experimental reference integrity failure: " + name)
    with (folder / "reference.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 10:
        raise ValueError("reference must contain ten nonimpaired muscle/axis observations")
    return rows, json.loads((folder / "reference.json").read_text(encoding="utf-8"))


def mesh_points(m, d, name):
    gid = m.geom(name).id
    mesh = m.geom_dataid[gid]
    vertices = m.mesh_vert[m.mesh_vertadr[mesh]:m.mesh_vertadr[mesh] + m.mesh_vertnum[mesh]]
    return vertices @ d.geom_xmat[gid].reshape(3, 3).T + d.geom_xpos[gid]


def long_axis(points, rotation):
    _, eigenvectors = np.linalg.eigh(np.cov(points.T))
    axis = eigenvectors[:, -1]
    return axis if (rotation.T @ axis)[1] < 0 else -axis


def geometry_frame(m, d):
    radius, hand = m.body("radius_r").id, m.body("hand_r").id
    rr, rh = d.xmat[radius].reshape(3, 3), d.xmat[hand].reshape(3, 3)
    distal = long_axis(mesh_points(m, d, "radius"), rr)
    hand_axis = long_axis(mesh_points(m, d, "sdfast_1seg_hand_fr_c_3mc"), rh)
    radial = (mesh_points(m, d, "sdfast_1seg_hand_fr_c_2mc").mean(0)
              - mesh_points(m, d, "sdfast_1seg_hand_fr_c_5mc").mean(0))
    radial -= distal * np.dot(radial, distal)
    radial /= np.linalg.norm(radial)
    dorsal = np.cross(distal, radial)
    return radius, hand, rr.T @ distal, rr.T @ radial, rr.T @ dorsal, rh.T @ hand_axis


def pose(mj, m, d, baseline, roots, equalities, coordinates):
    d.qpos[:] = baseline
    tangent = np.zeros((m.nv, 2))
    for column, (root, q) in enumerate(zip(roots, coordinates, strict=True)):
        d.qpos[m.jnt_qposadr[root]] = q
        tangent[m.jnt_dofadr[root], column] = 1
        for eq in equalities:
            if m.eq_obj2id[eq] != root:
                continue
            child = m.eq_obj1id[eq]
            x = q - m.qpos0[m.jnt_qposadr[root]]
            coefficients = m.eq_data[eq, :5]
            d.qpos[m.jnt_qposadr[child]] = m.qpos0[m.jnt_qposadr[child]] + np.polynomial.polynomial.polyval(x, coefficients)
            tangent[m.jnt_dofadr[child], column] = np.polynomial.polynomial.polyval(x, np.polynomial.polynomial.polyder(coefficients))
    for joint in [*roots, *(m.eq_obj1id[eq] for eq in equalities)]:
        q = d.qpos[m.jnt_qposadr[joint]]
        if m.jnt_limited[joint] and not m.jnt_range[joint, 0] <= q <= m.jnt_range[joint, 1]:
            raise ValueError("neutral wrist or derivative probe leaves source joint range")
    mj.mj_forward(m, d)
    return tangent


def angles_and_jacobian(mj, m, d, frame, tangent):
    radius, hand, distal, radial, dorsal, hand_axis = frame
    rr = d.xmat[radius].reshape(3, 3)
    h = rr.T @ d.xmat[hand].reshape(3, 3) @ hand_axis
    jp, jr_hand, jr_radius = [np.zeros((3, m.nv)) for _ in range(3)]
    mj.mj_jacBody(m, d, jp, jr_hand, hand)
    mj.mj_jacBody(m, d, jp, jr_radius, radius)
    angular_rates = rr.T @ (jr_hand - jr_radius) @ tangent
    derivatives = np.cross(angular_rates.T, h).T
    denominator = np.dot(h, distal)
    angles, jacobian = [], []
    for direction in (dorsal, -radial):
        numerator = np.dot(h, direction)
        angles.append(float(np.arctan2(numerator, denominator)))
        jacobian.append((denominator * direction @ derivatives - numerator * distal @ derivatives)
                        / (denominator**2 + numerator**2))
    return np.array(angles), np.array(jacobian)


def neutral_wrist(mj, m, d):
    frame = geometry_frame(m, d)
    roots = [m.joint(name).id for name in ("flexion_r", "deviation_r")]
    equalities = [eq for eq in range(m.neq) if m.eq_type[eq] == mj.mjtEq.mjEQ_JOINT
                  and m.eq_obj2id[eq] in roots and d.eq_active[eq]]
    if len(equalities) != 2:
        raise ValueError("expected two source wrist-to-hand equalities")
    baseline, q = d.qpos.copy(), d.qpos[m.jnt_qposadr[roots]].copy()
    initial_angles = None
    for _ in range(12):
        tangent = pose(mj, m, d, baseline, roots, equalities, q)
        angles, jacobian = angles_and_jacobian(mj, m, d, frame, tangent)
        if initial_angles is None:
            initial_angles = angles.copy()
        if np.linalg.cond(jacobian) > 10:
            raise ValueError("functional wrist coordinate mapping is ill conditioned")
        if max(abs(angles)) < 1e-11:
            break
        q -= np.linalg.solve(jacobian, angles)
    else:
        raise ValueError("geometric neutral wrist alignment did not converge")
    return frame, roots, equalities, baseline, q, tangent, jacobian, initial_angles


def benchmark(params: dict, output: Path, validation: dict) -> dict:
    rules = Validation.model_validate(validation).checks
    observed, source = reference()
    reference_folder = home() / "benchmarks/nichols2016_wrist"
    for original, artifact in (("article.xml", "reference_article.xml"), ("reference.csv", "experimental_reference.csv"),
                               ("reference.json", "reference_metadata.json")):
        shutil.copyfile(reference_folder / original, output / artifact)
    mj, m, d = load(dense_constraints=True)
    frame, roots, eqs, baseline, q, tangent, angular_jacobian, initial_angles = neutral_wrist(mj, m, d)
    inverse = np.linalg.inv(angular_jacobian)
    neutral_pose = d.qpos.copy()
    h = rules.jacobian_central_difference.step_rad
    rows = []
    for item in observed:
        axis = ("extension", "ulnar_deviation").index(item["axis"])
        aid = m.actuator(item["muscle"] + "_r").id
        direction = tangent @ inverse[:, axis]
        moment = -sum(moment_entry(m, d, aid, dof) * value for dof, value in enumerate(direction) if value)
        length = float(d.actuator_length[aid])
        probes, measured_angles = [], []
        for sign in (-1, 1):
            t = pose(mj, m, d, baseline, roots, eqs, q + sign * h * inverse[:, axis])
            angles, _ = angles_and_jacobian(mj, m, d, frame, t)
            probes.append(float(d.actuator_length[aid]))
            measured_angles.append(angles[axis])
        derivative = (probes[1] - probes[0]) / (measured_angles[1] - measured_angles[0])
        pose(mj, m, d, baseline, roots, eqs, q)
        mean, sd = float(item["mean_m"]), float(item["sd_m"])
        rows.append({"sample": len(rows), "muscle": item["muscle"], "axis": item["axis"], "angle_rad": 0.0,
                     "length_m": length, "moment_arm_m": float(moment), "experimental_mean_m": mean,
                     "experimental_sd_m": sd, "difference_m": float(moment - mean),
                     "jacobian_error_m_per_rad": abs(float(moment + derivative))})
    residuals = [abs(float(d.efc_pos[i])) for i in range(d.nefc)
                 if d.efc_type[i] == mj.mjtConstraint.mjCNSTR_EQUALITY and d.efc_id[i] in eqs]
    max_error = max(row["jacobian_error_m_per_rad"] for row in rows)
    if max_error > rules.jacobian_central_difference.absolute_tolerance_m_per_rad or max(residuals) > 1e-9:
        raise ValueError("functional wrist derivative or equality check failed")
    if not all(np.isfinite([r[k] for k in ("length_m", "moment_arm_m", "difference_m")]).all() and r["length_m"] > 0 for r in rows):
        raise ValueError("nonfinite benchmark measurement")
    metrics = [{"name": "rmse_" + axis, "value": float(np.sqrt(np.mean([r["difference_m"]**2 for r in rows if r["axis"] == axis]))), "unit": "m",
                "definition": "unweighted root-mean-square model-minus-published-mean difference across five muscles; no fitting"}
               for axis in ("extension", "ulnar_deviation")]
    metrics += [{"name": "max_jacobian_error", "value": max_error, "unit": "m/rad"},
                {"name": "max_wrist_equality_residual", "value": max(residuals), "unit": "rad"},
                {"name": "reference_observations", "value": len(rows), "unit": "1"}]
    protocol = {"source": source, "reference_hashes_verified": REFERENCE_HASHES,
        "coordinate_definition": "Signed radius/third-metacarpal PCA-long-axis angles: positive toward dorsal and ulnar directions; radial direction from fifth to second metacarpal mesh centroids.",
        "model_neutral_root_coordinates_rad": dict(zip((m.joint(i).name for i in roots), q.tolist(), strict=True)),
        "initial_geometric_angles_rad": initial_angles.tolist(), "neutral_geometric_angles_rad": angles_and_jacobian(mj, m, d, frame, tangent)[0].tolist(),
        "functional_angle_jacobian_rad_per_rad": angular_jacobian.tolist(),
        "model_radius_local_distal_axis": frame[2].tolist(), "model_radius_local_radial_axis": frame[3].tolist(),
        "model_hand_local_third_metacarpal_axis": frame[5].tolist(),
        "fit_to_experimental_values": False, "fit_scope": "No fitting by this benchmark; upstream calibration overlap with the published dataset has not been established.",
        "evidence_class": "descriptive_comparison_to_published_cadaver_means",
        "limitations": ["Generic model versus aggregate eight-cadaver data; no specimen scaling, individual raw trials, confidence intervals or clinical validation.",
                         "Model long axes use a declared mesh-PCA operationalization; experimental anatomical axis landmark details and subject postures are not reproduced exactly.",
                         "Only neutral nonimpaired wrist geometry is compared. SD is between specimens, not model uncertainty or an accuracy acceptance threshold.",
                         "Source joint names/partial moment arms are not directly compared: two linked carpal coordinates and the physical hand-angle coordinate transformation are included."]}
    protocol["limitations"].append("External to this implementation does not establish a held-out dataset: upstream calibration overlap is unknown.")
    for name, value in (("comparison.json", protocol), ("summary.json", {"metrics": metrics, "rows": rows}),
                        ("poses.json", {"model_id": "ms_human_700", "method": "static_pose", "simulation_time_s": 0.0,
                                        "integration_steps": 0, "qpos": [neutral_pose.tolist()] * len(rows)})):
        (output / name).write_text(json.dumps(value, indent=2), encoding="utf-8", newline="\n")
    with (output / "series.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    render_info = {"status": "not_requested", "render_backend": "none"}
    if params["render"]:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained", facecolor="#101923")
            for axis, name in zip(axes, ("extension", "ulnar_deviation"), strict=True):
                selected = [r for r in rows if r["axis"] == name]
                axis.set_facecolor("#101923")
                axis.tick_params(colors="#dfe7ef")
                x = np.arange(5)
                axis.errorbar(x, [1000*r["experimental_mean_m"] for r in selected], yerr=[1000*r["experimental_sd_m"] for r in selected],
                              fmt="o", capsize=4, color="#56c9d8", label="Published mean ± specimen SD (n=8)")
                axis.plot(x, [1000*r["moment_arm_m"] for r in selected], "s", color="#ffbd69", label="Generic model, no fitting")
                axis.set_xticks(x, [r["muscle"] for r in selected])
                axis.axhline(0, color="gray", linewidth=.6)
                axis.set_title("Positive " + name.replace("_", " "), color="#dfe7ef")
                axis.set_ylabel("Moment arm [mm]", color="#dfe7ef")
                axis.legend(fontsize=7, facecolor="#dfe7ef")
            fig.suptitle("MS-Human-700 / MuJoCo 3.17.0 vs Nichols et al. 2016 Table 2 | Neutral wrist geometry", color="#dfe7ef")
            fig.savefig(output / "plots.png", dpi=120)
            plt.close(fig)
            render_info = render(mj, m, d, output, neutral_pose.tolist(), len(rows)-1)
        except Exception as exc:
            render_info = {"status": "failed", "render_backend": "none", "message": str(exc)[:1000]}
    return {"status": "computed", "metrics": metrics, "render": render_info, "coordinate_mode": "geometric_neutral_coupled_wrist",
            "counts": {"nq": m.nq, "nv": m.nv, "actuators": m.nu, "tendons": m.ntendon}, "timestep_s": m.opt.timestep,
            "scientific_comparison": protocol, "citations": [{"title": "Nichols, Bednar and Murray (2016), Table 2", "url": source["url"], "doi": source["doi"]}],
            "checks": [{"name": name, "status": "pass"} for name in ("reference_integrity", "geometric_neutral_alignment", "wrist_equalities", "functional_coordinate_finite_difference")],
            "time_series": {"artifact_id": "series.csv", "axis": "muscle/functional axis at one neutral pose (not time)",
                            "units": {"length_m": "m", "moment_arm_m": "m", "experimental_mean_m": "m", "experimental_sd_m": "m", "difference_m": "m", "angle_rad": "rad", "jacobian_error_m_per_rad": "m/rad"},
                            "definition": "Moment arms transformed to physical hand-angle derivatives, compared descriptively with published experimental means; no fitting."}}
