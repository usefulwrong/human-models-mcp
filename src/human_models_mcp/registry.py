"""Declarative scenarios: data only, restricted to the installed backend."""

import os
from pathlib import Path
from typing import Literal

import yaml
from .runtime.paths import is_link

from pydantic import BaseModel, ConfigDict, Field, model_validator


def home() -> Path:
    return Path(os.environ.get("HUMAN_MODELS_HOME", ".")).resolve()


class SweepParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    joint: str = Field(default="elbow_flexion_r", min_length=1, max_length=100)
    muscle: str = Field(default="BIClong_r", min_length=1, max_length=100)
    start_rad: float = Field(default=0.2, ge=-3.0, le=3.0)
    end_rad: float = Field(default=1.8, ge=-3.0, le=3.0)
    samples: int = Field(default=9, ge=3, le=101)
    render: bool = True
    coordinate_mode: Literal["fixed", "coupled_knee"] = "fixed"

    @model_validator(mode="after")
    def ordered(self):
        if self.end_rad <= self.start_rad:
            raise ValueError("end_rad must exceed start_rad")
        return self


class ForwardParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    muscle: str = Field(default="BIClong_r", min_length=1, max_length=100)
    excitation: float = Field(default=0.3, ge=0, le=1)
    steps: int = Field(default=10, ge=1, le=25)
    render: bool = True


class LoadedParameters(ForwardParameters):
    muscle: Literal["BIClong_r"] = "BIClong_r"
    joint: Literal["elbow_flexion_r"] = "elbow_flexion_r"
    excitation: float = Field(default=0.15, ge=0, le=0.5)
    steps: int = Field(default=100, ge=25, le=200)
    torque_Nm: float = Field(default=2.0, ge=-5, le=5)
    timestep_s: Literal[0.001, 0.002] = 0.002


class WristParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    render: bool = True
    joint: Literal["flexion_r"] = "flexion_r"
    muscle: Literal["FCR_r"] = "FCR_r"
    samples: Literal[10] = 10
    reference_id: Literal["nichols2016_table2_nonimpaired"] = "nichols2016_table2_nonimpaired"


class TrackingParameters(LoadedParameters):
    controller: Literal["joint_pd"] = "joint_pd"
    excitation: float = Field(default=0.0, ge=0, le=0.2)
    torque_Nm: Literal[0.0] = 0.0
    target_rad: float = Field(default=0.4, ge=0.1, le=0.6)
    steps: int = Field(default=200, ge=200, le=400, description="Exactly 0.4 s: 200 steps at 0.002 s or 400 steps at 0.001 s")

    @model_validator(mode="after")
    def fixed_duration(self):
        if abs(self.steps * self.timestep_s - 0.4) > 1e-12:
            raise ValueError("tracking requires 0.4 s: 200 steps at 0.002 s or 400 at 0.001 s")
        return self


class ContactParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    scene: Literal["locomotion_floor_v1"] = "locomotion_floor_v1"
    assistance: Literal["none"] = "none"
    duration_s: Literal[0.2] = 0.2
    steps: int = Field(default=100, ge=100, le=400)
    timestep_s: Literal[0.001, 0.002] = 0.002
    root_height_offset_m: float = Field(default=0.0, ge=-0.03, le=0.03,
        description="Offset from a geometrically aligned 0.2 mm sole clearance. Initial penetration or missing foot contact is rejected by the engine preflight.")
    initial_velocity_x_m_per_s: float = Field(default=0.0, ge=-0.05, le=0.05)
    downward_load_N: float = Field(default=0.0, ge=0, le=100)
    render: bool = True

    @model_validator(mode="after")
    def fixed_duration(self):
        if abs(self.steps * self.timestep_s - self.duration_s) > 1e-12:
            raise ValueError("step count times timestep must equal this scenario's fixed duration")
        return self


class AssistedContactParameters(ContactParameters):
    assistance: Literal["pelvis_pd"] = "pelvis_pd"
    duration_s: Literal[0.4] = 0.4
    steps: int = Field(default=200, ge=100, le=400)
    assist_gain_scale: float = Field(default=1.0, ge=0.5, le=1.5)


class PushupParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    control: Literal["muscle", "external", "assisted_muscle"] = "muscle"
    hand_support: Literal["legacy_point", "palms", "knuckles"] = "legacy_point"
    support_boundary: Literal["frictional", "fixed_points", "frictional_contact"] = "frictional"
    contact_profile: Literal["surface_spheres_v1", "surface_convex_v1", "articulated_palms_v1"] | None = Field(default=None, exclude_if=lambda value: value is None)
    knuckle_technique: Literal["legacy_flared", "neutral_tucked"] = "legacy_flared"
    palm_technique: Literal["legacy_reach", "chest_level", "chest_full"] = "legacy_reach"
    muscle_strength_scale: float = Field(default=1.0, ge=0, le=1)
    friction: float = Field(default=1.3, ge=0.05, le=1.5)
    timestep_s: Literal[0.001, 0.0005] = 0.001
    render: Literal[False] = False

    @model_validator(mode="after")
    def sticking_requires_detailed_hand(self):
        if self.support_boundary == "fixed_points" and self.hand_support == "legacy_point":
            raise ValueError("fixed support points require the palms or knuckles hand geometry")
        if self.knuckle_technique == "neutral_tucked" and (self.hand_support != "knuckles" or self.support_boundary != "fixed_points"):
            raise ValueError("neutral tucked technique requires fixed-points knuckle support")
        if self.support_boundary == "frictional_contact":
            if self.contact_profile is None or self.hand_support != "palms" or self.palm_technique != "chest_full":
                raise ValueError("experimental contact requires a surface profile and full chest-level palms")
        elif self.contact_profile is not None:
            raise ValueError("surface profiles require frictional_contact support")
        if self.palm_technique in ("chest_level", "chest_full") and (self.hand_support != "palms" or self.support_boundary not in ("fixed_points", "frictional_contact")):
            raise ValueError("chest-level palms require fixed-points palm support")
        return self


PARAMETER_TYPES = {"joint_sweep": SweepParameters, "activation_forward": ForwardParameters,
                   "loaded_elbow": LoadedParameters, "wrist_benchmark": WristParameters, "elbow_tracking": TrackingParameters,
                   "standing_contact_probe": ContactParameters, "assisted_stance": AssistedContactParameters,
                   "pushup": PushupParameters}


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    title: str = Field(min_length=1, max_length=160)
    engine: Literal["mujoco"]
    engine_version: Literal["3.17.0"]
    model: Literal["ms_human_700", "ms_human_700_locomotion"]
    model_revision: Literal["98a70c569c4c1b6da467a20012f766ee1f8dc521"]
    backend: Literal["joint_sweep", "activation_forward", "loaded_elbow", "wrist_benchmark", "elbow_tracking", "standing_contact_probe", "assisted_stance", "pushup"]
    method: Literal["static_pose", "dynamic_forward"]
    required_capabilities: list[Literal["musculotendon_length", "moment_arm", "dynamic_forward", "muscle_activation", "actuator_force", "coupled_knee_kinematics", "loaded_elbow", "motion_visualization", "experimental_reference_comparison", "joint_pd_tracking", "contact_probe", "ground_reaction_forces", "center_of_mass", "support_polygon", "externally_assisted_dynamics", "feedback_tracking", "muscle_actuated_dynamics"]]
    scope: str = Field(min_length=10, max_length=2000)
    defaults: SweepParameters | ForwardParameters | LoadedParameters | WristParameters | TrackingParameters | ContactParameters | AssistedContactParameters | PushupParameters

    @model_validator(mode="after")
    def compatible_backend(self):
        contact = self.backend in ("standing_contact_probe", "assisted_stance")
        if (self.model == "ms_human_700_locomotion") != contact:
            raise ValueError("contact backends require the locomotion model; existing backends require the primary model")
        if self.backend == "wrist_benchmark":
            if self.method != "static_pose" or not isinstance(self.defaults, WristParameters):
                raise ValueError("wrist_benchmark requires static_pose and fixed benchmark parameters")
        elif self.backend == "joint_sweep":
            if self.method != "static_pose" or not isinstance(self.defaults, SweepParameters):
                raise ValueError("joint_sweep requires static_pose and sweep parameters")
        else:
            expected = {"loaded_elbow": LoadedParameters, "elbow_tracking": TrackingParameters,
                        "activation_forward": ForwardParameters, "standing_contact_probe": ContactParameters,
                        "assisted_stance": AssistedContactParameters, "pushup": PushupParameters}[self.backend]
            if self.method != "dynamic_forward" or type(self.defaults) is not expected:
                raise ValueError("dynamic backend and parameter schema do not match")
        return self


class DifferenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    step_rad: float = Field(gt=0, le=0.0001)
    absolute_tolerance_m_per_rad: float = Field(gt=0, le=0.00001)


class SignCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path_length_change: Literal["positive", "negative"]
    signed_moment_arms: Literal["positive", "negative"]


class SweepChecks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    finite_positive_path_lengths: Literal[True]
    jacobian_central_difference: DifferenceCheck
    repeat_run_absolute_tolerance_m: float = Field(gt=0, le=0.000000000001)
    default_configuration: SignCheck | None = None


class Validation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    validation_level: Literal["numerical_sanity"]
    checks: SweepChecks
    limitations: str = Field(min_length=10, max_length=2000)


class ForwardChecks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    finite_state: Literal[True]
    zero_engine_warnings: Literal[True]
    activation_bounds: Literal[True]
    repeat_run_absolute_tolerance: float = Field(gt=0, le=1e-10)


class ForwardValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    validation_level: Literal["numerical_sanity"]
    checks: ForwardChecks
    limitations: str = Field(min_length=10, max_length=2000)


class ContactChecks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    finite_state: Literal[True]
    zero_engine_warnings: Literal[True]
    contact_map: Literal["upstream_capsules_and_plane"]
    force_balance_tolerance_N: float = Field(gt=0, le=0.0001)
    moment_balance_tolerance_Nm: float = Field(gt=0, le=0.0001)
    kinematic_difference_step_s: float = Field(gt=0, le=0.00001)
    max_penetration_m: float = Field(gt=0, le=0.005)
    max_hinge_limit_violation_rad: float = Field(gt=0, le=0.001)
    max_slide_limit_violation_m: float = Field(gt=0, le=0.0001)
    friction_tolerance_N: float = Field(gt=0, le=0.000001)
    repeat_run_absolute_tolerance: float = Field(gt=0, le=1e-10)


class ContactValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    validation_level: Literal["numerical_sanity"]
    checks: ContactChecks
    limitations: str = Field(min_length=10, max_length=2000)


def discover(root: Path | None = None) -> dict:
    root = root or home() / "scenarios"
    valid, invalid = [], []
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not folder.is_dir():
            continue
        try:
            if is_link(folder):
                raise ValueError("symlinked scenario folders are forbidden")
            manifest = folder / "scenario.yaml"
            if is_link(manifest) or manifest.stat().st_size > 16384:
                raise ValueError("manifest must be a regular file <=16 KiB")
            for name in ("README.md", "references.md", "validation.yaml"):
                p = folder / name
                if is_link(p) or not p.is_file():
                    raise ValueError(f"missing regular {name}")
            scenario = Scenario.model_validate(yaml.safe_load(manifest.read_text(encoding="utf-8")))
            validation_file = folder / "validation.yaml"
            if validation_file.stat().st_size > 16384:
                raise ValueError("validation.yaml exceeds 16 KiB")
            validator = ContactValidation if scenario.backend in ("standing_contact_probe", "assisted_stance") else Validation if scenario.method == "static_pose" else ForwardValidation
            validation = validator.model_validate(yaml.safe_load(validation_file.read_text(encoding="utf-8")))
            if scenario.id != folder.name:
                raise ValueError("scenario id must equal folder name")
            schema = PARAMETER_TYPES[scenario.backend].model_json_schema()
            for name, value in scenario.defaults.model_dump().items():
                schema["properties"][name]["default"] = value
            valid.append({**scenario.model_dump(), "validation": validation.model_dump(),
                          "parameter_schema": schema})
        except (OSError, ValueError, yaml.YAMLError) as exc:
            invalid.append({"id": folder.name, "status": "invalid_manifest", "message": str(exc)[:1500]})
    return {"scenarios": valid, "quarantined": invalid}
