"""Lightweight metadata. Listing models never imports MuJoCo or NumPy."""

import hashlib
import importlib.metadata
import json

from .registry import home

MODEL_FILES = {"ms_human_700": "MS-Human-700.xml", "ms_human_700_locomotion": "scene_locomotion.xml"}

LIMITATIONS = [
    "Model-specific musculotendon geometry; no population normative or patient-specific claims.",
    "No organ, disc pressure, spinal cord, breathing, injury risk, or medical safety predictions.",
    "No equilibrium controller, gait policy, observed motion replay, or human force validation.",
    "Numerical consistency is not experimental or clinical validation; wrapping branches can be nonsmooth.",
]
SWEEP_LIMITATIONS = [
    "Prescribed independent coordinates; other qpos stay at upstream init, including equality-coupled coordinates.",
    "Partial derivatives, not constrained physiological moment arms; no time integration or force estimate in sweeps.",
]
FORWARD_LIMITATIONS = [
    "Short uncontrolled initial-value simulation, not standing, exercise, gait, or a measured human movement.",
    "Full primary model with gravity and no scene floor; all excitations zero except the selected actuator.",
    "Initial qpos is upstream init, qvel/activation zero; no equilibrium or initial-state calibration.",
    "Signed actuator force is the model's transmission force, not validated biological force, joint reaction, or injury risk.",
]
COUPLED_LIMITATIONS = [
    "Only the eight source equalities for the selected knee are enforced on this prescribed coordinate path.",
    "Other coordinates remain at upstream init; unrelated equalities, equilibrium and complete collision validity are not established.",
    "Effective moment arm is -dL/dq along the model's local equality path, not experimental physiological validation.",
]
CITATIONS = [
    {"title": "MS-Human-700 Menagerie model card and citation", "url": "https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700"},
    {"title": "Zuo et al., Self model for embodied intelligence, ICRA 2024, pp. 13062–13069", "url": "https://github.com/LNSGroup/MS-Human-700"},
    {"title": "MuJoCo computation: transmissions and moment arms", "url": "https://mujoco.readthedocs.io/en/3.17.0/computation/index.html"},
]


def model_card(verify: bool = False, model_id: str = "ms_human_700") -> dict:
    if model_id not in MODEL_FILES:
        return {"status": "unsupported", "error": {"code": "unsupported", "message": "no installed model adapter"}}
    lock = json.loads((home() / "models.lock.json").read_text())
    files = lock["files"]
    missing = [x["path"] for x in files if not (home() / "models" / x["path"]).is_file()]
    corrupt = []
    if verify and not missing:
        corrupt = [x["path"] for x in files
                   if (home() / "models" / x["path"]).is_symlink()
                   or hashlib.sha256((home() / "models" / x["path"]).read_bytes()).hexdigest() != x["sha256"]]
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if digest != lock["asset_sha256"]:
            corrupt.append("models.lock.json aggregate digest")
    try:
        engine_version = importlib.metadata.version("mujoco")
    except importlib.metadata.PackageNotFoundError:
        engine_version = None
    status = "available"
    if missing or engine_version is None:
        status = "not_installed"
    elif corrupt or engine_version != "3.17.0":
        status = "unavailable"
    card = {"id": model_id, "status": status, "source_url": lock["source_url"],
            "revision": lock["revision"], "asset_sha256": lock["asset_sha256"], "license": lock["license"],
            "variant": "MS-Human-700.xml primary; hand detail differs from manipulation variant",
            "engine": {"name": "mujoco", "version": engine_version},
            "integrity": "verified" if verify and status == "available" else "not_verified",
            "missing_files": missing[:5], "corrupt_files": corrupt[:5],
            "capabilities": ["static_pose", "musculotendon_length", "moment_arm", "joint_info", "headless_render",
                             "dynamic_forward", "muscle_activation", "actuator_force", "coupled_knee_kinematics", "loaded_elbow", "motion_visualization", "experimental_reference_comparison", "joint_pd_tracking"],
            "unsupported": ["inverse_dynamics", "physiology",
                            "pushup", "running", "walking", "standing_and_breathing", "breathing", "defecation",
                            "medical_safety", "extreme_pose_safety", "injury_risk", "disc_pressure", "spinal_cord",
                            "sex_customization", "sex_specific_anatomy", "age_customization", "pathology", "anthropometric_scaling",
                            "standing_balance", "externally_actuated_balance", "neuromuscular_balance", "zmp"],
            "units": {"hinge_coordinate": "rad", "slide_coordinate": "m", "musculotendon_length": "m",
                      "hinge_moment_arm": "m", "mass": "kg"},
            "acceleration": {"physics_backend": "cpu", "render_backend": "osmesa or verified nvidia_egl"},
            "limitations": LIMITATIONS, "method_limitations": {
                "static_pose": ["No integration; read the scenario for fixed-coordinate, local-coupled or physical-wrist-coordinate semantics."],
                "dynamic_forward": ["Read the scenario for source initialization, fixture, control law and applied forces; no clinical safety inference."],
                "fixed_coordinate_sweep": SWEEP_LIMITATIONS, "activation_pulse": FORWARD_LIMITATIONS},
            "evidence_summary": {"experimental_comparison": "wrist_benchmark compares ten neutral-wrist moment arms with published cadaver means; coordinate/posture limitations apply.",
                                 "experimentally_validated_model": False, "clinically_validated": False,
                                 "other_scenarios": "numerical checks only; do not inherit the wrist comparison"}, "citations": CITATIONS}
    card["source_files"] = [{"path": item["path"], "sha256": item["sha256"]} for item in files
                            if item["path"] == "ms_human_700/" + MODEL_FILES[model_id]]
    if model_id == "ms_human_700":
        card["capabilities"] += ["feedback_tracking", "muscle_actuated_dynamics", "pushup_research", "all_actuator_time_series"]
        card["unsupported"].remove("pushup")
        card["method_limitations"]["pushup"] = [
            "Research scenario uses 700 muscles, added mechanical palm/toe pads, extra internal damping and synthetic feedback targets.",
            "Read separate exercise, contact, numerical and muscle-driven acceptance gates; no human or volumetric-anatomy validation."]
    else:
        card.update(variant="MS-Human-700-Locomotion.xml with upstream scene_locomotion.xml floor; 100 lower-body muscle actuators",
                    citations=CITATIONS + [
                        {"title": "MuJoCo 3.17.0 contacts: frame rows, force decoding and soft constraints", "url": "https://mujoco.readthedocs.io/en/3.17.0/programming/simulation.html#contacts"},
                        {"title": "MuJoCo 3.17.0 engine: contact wrench sign on geom1", "url": "https://github.com/google-deepmind/mujoco/blob/3.17.0/src/engine/engine_core_smooth.c"}],
                    capabilities=["joint_info", "dynamic_forward", "headless_render", "motion_visualization", "contact_probe",
                                  "ground_reaction_forces", "center_of_mass", "support_polygon", "externally_assisted_dynamics"],
                    limitations=["Generic 60.219 kg model with simplified upper body and native capsule contacts; no subject-specific or clinical validation.",
                                 "Probe is a short passive contact transient; assisted_stance applies an explicit external pelvis wrench.",
                                 "No unsupported standing balance, gait policy, organs, sex customization or medical safety outputs.",
                                 "Contact margins/soft constraints are model settings, not tissue deformation or complete self-collision."],
                    method_limitations={"dynamic_forward": ["Read model_recipe.json, initialization, support wrench, momentum checks and the actual scenario; no equilibrium or neuromuscular balance claim."]},
                    evidence_summary={"experimental_comparison": "none for the locomotion contact experiment; primary-model wrist comparison does not transfer",
                                      "experimentally_validated_model": False, "clinically_validated": False,
                                      "numerical_checks": "contact-frame forces, COM/angular-momentum dynamics, named geometry/limit checks; see each run"})
        card["source_files"] += [{"path": item["path"], "sha256": item["sha256"]} for item in files
                                 if item["path"] == "ms_human_700/MS-Human-700-Locomotion.xml"]
    return card
