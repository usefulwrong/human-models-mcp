"""Local knee path from source equalities; no physiological/clinical validation."""

import numpy as np


def knee_equalities(mj, m, d, joint: int) -> list[int]:
    if m.joint(joint).name not in ("knee_angle_r", "knee_angle_l"):
        raise ValueError("coupled_knee supports only the source right/left knee angle")
    ids = [i for i in range(m.neq) if m.eq_type[i] == mj.mjtEq.mjEQ_JOINT
           and m.eq_obj2id[i] == joint and d.eq_active[i]]
    if len(ids) != 8:
        raise ValueError("expected the eight pinned tibial/patellar knee equalities")
    return ids


def set_path(m, d, baseline, joint: int, angle: float, equalities: list[int]):
    d.qpos[:] = baseline
    qa = int(m.jnt_qposadr[joint])
    d.qpos[qa] = angle
    tangent = np.zeros(m.nv)
    tangent[m.jnt_dofadr[joint]] = 1
    x = angle - m.qpos0[qa]
    for eq in equalities:
        dependent = int(m.eq_obj1id[eq])
        address = int(m.jnt_qposadr[dependent])
        coefficients = m.eq_data[eq, :5]
        d.qpos[address] = m.qpos0[address] + np.polynomial.polynomial.polyval(x, coefficients)
        if m.jnt_limited[dependent] and not m.jnt_range[dependent, 0] - 1e-8 <= d.qpos[address] <= m.jnt_range[dependent, 1] + 1e-8:
            raise ValueError("coupled coordinate exceeds a source model joint range: " + m.joint(dependent).name)
        tangent[m.jnt_dofadr[dependent]] = np.polynomial.polynomial.polyval(x, np.polynomial.polynomial.polyder(coefficients))
    return tangent


def validate_interval(m, joint: int, equalities: list[int], low: float, high: float):
    reference = float(m.qpos0[m.jnt_qposadr[joint]])
    for eq in equalities:
        dependent = int(m.eq_obj1id[eq])
        coefficients = m.eq_data[eq, :5]
        critical = np.polynomial.polynomial.polyroots(np.polynomial.polynomial.polyder(coefficients))
        points = [low - reference, high - reference]
        points.extend(float(x.real) for x in critical if abs(x.imag) < 1e-12 and low - reference <= x.real <= high - reference)
        values = m.qpos0[m.jnt_qposadr[dependent]] + np.polynomial.polynomial.polyval(points, coefficients)
        if m.jnt_limited[dependent] and (min(values) < m.jnt_range[dependent, 0] - 1e-8 or max(values) > m.jnt_range[dependent, 1] + 1e-8):
            raise ValueError("source equality path conflicts with joint limits over this interval: " + m.joint(dependent).name)


def constraint_checks(mj, m, d, joint: int, equalities: list[int], tangent) -> dict:
    rows = [next(i for i in range(d.nefc) if d.efc_type[i] == mj.mjtConstraint.mjCNSTR_EQUALITY
                 and d.efc_id[i] == eq) for eq in equalities]
    jacobian = d.efc_J.reshape(d.nefc, m.nv)[rows]
    columns = [int(m.jnt_dofadr[m.eq_obj1id[eq]]) for eq in equalities]
    # Independently solve the engine's constraint tangent, without reading polycoef.
    implicit = np.linalg.solve(jacobian[:, columns], -jacobian[:, int(m.jnt_dofadr[joint])])
    translation, rotation = [], []
    for eq, row in zip(equalities, rows, strict=True):
        residuals = translation if m.jnt_type[m.eq_obj1id[eq]] == mj.mjtJoint.mjJNT_SLIDE else rotation
        residuals.append(abs(float(d.efc_pos[row])))
    errors = abs(implicit - tangent[columns])
    slide_errors = [float(value) for eq, value in zip(equalities, errors, strict=True)
                    if m.jnt_type[m.eq_obj1id[eq]] == mj.mjtJoint.mjJNT_SLIDE]
    hinge_errors = [float(value) for eq, value in zip(equalities, errors, strict=True)
                    if m.jnt_type[m.eq_obj1id[eq]] == mj.mjtJoint.mjJNT_HINGE]
    result = {"translation_residual_m": max(translation, default=0),
              "rotation_residual_rad": max(rotation, default=0),
              "translation_tangent_error_m_per_rad": max(slide_errors, default=0),
              "rotation_tangent_error_rad_per_rad": max(hinge_errors, default=0)}
    if max(result.values()) > 1e-9:
        raise ValueError("local knee constraints or independent tangent check failed")
    return result
