"""Shared provenance for saved quantities. Values remain in their existing response fields."""

NATIVE = "native_numeric_output"
DERIVED = "deterministic_derived_value"
ILLUSTRATIVE = "illustrative_visualization"


SUBJECT_CALIBRATION = ("Use subject geometry and calibrate inertial and strength parameters from matched measurements. "
                       "Reserve independent trials for comparison.")
EMG_TIMING = ("Compare timing with independently recorded, synchronized EMG for the same task and muscle region. "
              "Amplitude requires a separate observation model.")
CONTACT_FORCE = ("Compare time-aligned world-frame reactions summed per support with synchronized force plates "
                 "under the same task and support conditions.")
PRESSURE = "Measure the spatial and temporal pressure field directly with calibrated skin-interface pressure sensors."


def quantity(unit, definition, origin=NATIVE, availability="AVAILABLE", *, native_identifier=None,
             estimate=SUBJECT_CALIBRATION):
    return {"unit": unit, "definition": definition, "origin": origin, "availability": availability,
            "native_identifier": native_identifier, "improve_estimate": estimate}


MUSCLE = {
    "activation": quantity("1", "Modeled 0–1 actuator state at the actuator activation address.",
                           native_identifier="mjData.act", estimate=EMG_TIMING),
    "excitation": quantity("1", "Recorded 0–1 input at the actuator index.",
                           native_identifier="mjData.ctrl",
                           estimate="Compare predicted activation timing against synchronized EMG using an explicit excitation-to-activation model."),
    "force_N": quantity("N", "Signed scalar transmission force at the actuator index. Tension generally has negative sign.",
                        native_identifier="mjData.actuator_force"),
    "force_magnitude_N": quantity("N", "Absolute value of the signed scalar actuator transmission force.", DERIVED),
    "length_m": quantity("m", "Modeled transmission-path length, with fiber and tendon reported together.",
                         native_identifier="mjData.actuator_length"),
    "velocity_m_per_s": quantity("m/s", "Signed rate of change of modeled transmission length.",
                                 native_identifier="mjData.actuator_velocity"),
    "power_W": quantity("W", "Signed transmission force multiplied by signed transmission velocity. A sum across paths is model mechanical power for those paths.", DERIVED),
    "work_J": quantity("J", "Cumulative trapezoidal integral of signed transmission power from the first saved sample, before windowing or stride.", DERIVED),
    "full_integrator_work_J": quantity("J", "Left-endpoint sum of signed transmission power times the solver timestep over the full push-up run.", DERIVED),
    "overlay": quantity("1", "Uniform RGB per linked mesh from the arithmetic mean of saved native path activations.", ILLUSTRATIVE,
                        estimate=EMG_TIMING),
    "display_surface": quantity("m", "Illustrative replay of a source mesh. Mesh skinning describes displayed geometry. "
                                "Volumetric tissue stress and strain are unavailable.", ILLUSTRATIVE,
                                estimate="Register segmented subject anatomy and independently track tissue deformation under load."),
}

CONTACT = {
    "normal_force_N": quantity("N", "Normal force component for one native collision pair at a saved state.",
                               native_identifier="mj_contactForce[0]", estimate=CONTACT_FORCE),
    "local_force_N": quantity("N", "Force in the native contact frame acting on geom1. The opposite force acts on geom0.",
                              native_identifier="mj_contactForce[0:3]", estimate=CONTACT_FORCE),
    "local_torque_Nm": quantity("N*m", "Torque in the native contact frame acting on geom1 about the contact point.",
                               native_identifier="mj_contactForce[3:6]", estimate=CONTACT_FORCE),
    "force_on_geom1_world_N": quantity("N", "Transpose of the contact frame matrix times the local force on geom1.",
                                       DERIVED, estimate=CONTACT_FORCE),
    "torque_on_geom1_world_Nm": quantity("N*m", "Transpose of the contact frame matrix times the local torque on geom1.",
                                         DERIVED, estimate=CONTACT_FORCE),
    "position_m": quantity("m", "Native contact point in right-handed Z-up world coordinates.", native_identifier="mjContact.pos"),
    "frame_rows": quantity("1", "Native contact frame basis rows in world axes. Row zero is the contact normal.",
                           native_identifier="mjContact.frame"),
    "friction": quantity("mixed", "Native contact coefficients ordered as two sliding, one torsional and two rolling coefficients. Sliding is dimensionless and torsional/rolling are in metres.",
                         native_identifier="mjContact.friction",
                         estimate="Measure friction and compliance of the actual surfaces under the relevant loading conditions."),
    "gap_m": quantity("m", "Native collision-pair distance. Negative values indicate modeled overlap.",
                      native_identifier="mjContact.dist"),
    "inclusion_margin_m": quantity("m", "Distance below which the contact constraint is eligible for inclusion.",
                                   native_identifier="mjContact.includemargin"),
    "signed_distance_m": quantity("m", "Minimum signed distance of mapped rigid display vertices to the modeled floor plane.", DERIVED),
    "vertex_world_m": quantity("m", "World position of the mapped display vertex at the reported minimum floor distance.", DERIVED),
    "total_normal_force_N": quantity("N", "Scalar sum of the selected part’s floor-pair normal components at one saved state, counting each event once. Compare force plates with the world-frame reaction.",
                                     DERIVED, estimate=CONTACT_FORCE),
    "skin_contact_pressure": quantity("Pa", "Skin stress normal to a resolved skin patch. Collision proxies provide no skin area or pressure field.",
                                      None, "NOT_MODELED", estimate=PRESSURE),
}

PUSHUP_SUMMARY = {
    "max_support_slip_m": "Maximum horizontal displacement from initial pad positions over solver steps, also including guide displacements when fixed supports are used.",
    "max_hinge_limit_violation_rad": "Maximum positive excursion of any monitored hinge past either source or declared model bound over solver steps, clamped at zero.",
    "external_work_J": "Left-endpoint sum of applied generalized force dotted with generalized velocity, times the solver timestep.",
}

PUSHUP_METRICS = {
    **PUSHUP_SUMMARY,
    "chest_excursion_m": "Height of the mean humerus body origins at the first state minus its minimum over saved states.",
    "chest_return_error_m": "Absolute change in the mean humerus body origin height between the first and last saved states.",
    "min_support_fraction": "Smallest fraction, over the four support groups, of assessed solver steps at or above 0.2 s with normal load above 1 N.",
    "max_penetration_m": "Maximum of zero and minus native contact distance over simulated steps.",
    "max_slide_limit_violation_m": "Maximum positive excursion of any monitored slide past either model bound over solver steps, clamped at zero.",
    "max_force_balance_error_N": "Maximum saved-state norm of mass times COM acceleration minus support reaction minus weight vector.",
    "max_moment_balance_error_Nm": "Maximum saved-state norm of angular momentum rate minus support moment about the whole-body COM.",
    "max_transmission_sum_error": "Maximum saved-state absolute component error of the transmission Jacobian transpose times native forces versus qfrc_actuator.",
    "max_friction_violation_N": "Largest recorded positive friction-cone residual. The fixed-support run also tests each combined support reaction.",
    "max_external_generalized_force": "Maximum absolute component of qfrc_applied over solver steps.",
    "max_plank_joint_deviation_rad": "Largest absolute monitored plank coordinate over solver steps.",
    "max_wrist_shaft_extension_rad": "Maximum geometric wrist-shaft extension over both hands and all solver steps.",
    "max_support_point_displacement_m": PUSHUP_SUMMARY["max_support_slip_m"],
    "max_support_point_speed_m_per_s": "Largest reported fixed guide reaction marker speed over solver steps.",
    "support_constraint_work_J": "Left-endpoint sum of guide reaction power times the solver timestep across fixed guides.",
    "max_wrist_ahead_head_m": "Maximum world x coordinate of the hand body origin minus that of the skull geom centre, over both sides and settled saved states.",
    "max_wrist_ahead_shoulder_m": "Maximum world x coordinate of the hand body origin minus that of the ipsilateral shoulder anchor, over both sides and settled saved states.",
    "max_palm_shoulder_chest_gap_m": "Maximum distance of palm support from the shoulder-to-caudal-sternum longitudinal band over both sides and settled saved states.",
    "max_palm_ahead_shoulder_m": "Maximum signed longitudinal palm support position ahead of the ipsilateral shoulder over both sides and settled saved states.",
    "min_fingers_forward_cosine": "Minimum projection of the negative hand-frame Y axis on world positive X, over both sides and settled saved states.",
    "bottom_shoulder_above_elbow_m": "Larger of the two shoulder-minus-elbow heights at the minimum saved chest height.",
}
PUSHUP_METRICS.update({
    f"{support}_max_material_marker_drift_m":
        "Maximum horizontal displacement from initial position among collision pad centres for the named support, over solver steps."
    for support in ("palm_l", "palm_r", "toe_l", "toe_r")
})


def sources(run, *names):
    inventory = run.get("artifacts", {})
    return {name: inventory[name]["sha256"] for name in dict.fromkeys(names) if "sha256" in inventory.get(name, {})}


def scientific_quantity(run, quantities, *, files=None, window=None, uncertainty=(), comparison=None):
    model = run.get("model", {})
    execution = run.get("execution", {})
    parameters = execution.get("parameters", {})
    controller = execution.get("controller") or {}
    derivation = model.get("derivation") or {}
    acceptance = run.get("scientific", {}).get("acceptance", {})
    support = parameters.get("support_boundary", derivation.get("support_boundary"))
    fixed = {"fixed_points": "USED", "frictional_contact": "NOT_USED"}.get(support, "NOT_AVAILABLE")
    if acceptance.get("no_world_support_equalities") == "FAIL":
        fixed = "USED"
    return {
        "schema_version": "hmm.scientific_quantity/1",
        "run_id": run.get("run_id"),
        "scenario": {"id": run.get("scenario_id"), "version": run.get("scenario_version"), "sha256": run.get("scenario_sha256")},
        "model": {k: model[k] for k in ("id", "revision", "asset_sha256", "source_url", "source_files") if k in model}
                 | {k: derivation[k] for k in ("version", "derived_mjcf_sha256") if k in derivation},
        "controls": {"mode": controller.get("mode", parameters.get("control", "NOT_AVAILABLE")),
                     "joint_assistance": controller.get("assistance", "NOT_AVAILABLE"),
                     "external_control": acceptance.get("external_control", "NOT_AVAILABLE"),
                     "support_boundary": support or "NOT_AVAILABLE", "fixed_support_equalities": fixed,
                     "resolved_parameters": parameters,
                     "parameter_default_provenance": execution.get("parameter_origins", "NOT_AVAILABLE")},
        "acceptance": acceptance,
        "reference_comparison": comparison or {"status": "NOT_AVAILABLE", "execution_status": "NOT_RUN"},
        "human_validation": acceptance.get("human_experimental_validation", "NOT_VALIDATED"),
        "window": window,
        "sources_sha256": files or {},
        "quantities": quantities,
        "uncertainty_sources": list(uncertainty),
        "uncertainty_interval": {"status": "NOT_AVAILABLE",
                                 "reason": "No uncertainty model or independent error distribution is recorded. Use a specified "
                                           "measurement protocol and propagate its errors and calibrated parameter uncertainty."},
        "physiological_scaling": {"status": "NOT_RUN", "reason": SUBJECT_CALIBRATION},
    }
