"""Typed public Muscle Intelligence operations, shared by the HTTP and MCP adapters."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Metric = Literal["activation", "excitation", "force_N", "force_magnitude_N", "length_m", "velocity_m_per_s",
                 "power_W", "work_J"]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Index = Annotated[int, Field(strict=True, ge=0, le=699)]
Node = Annotated[int, Field(strict=True, ge=0, le=4095)]
Group = Annotated[str, Field(pattern=r"^[a-z_]{1,40}:(left|right)$")]


class MuscleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MuscleRequest(MuscleModel):
    run_id: UUID


class MuscleSearch(MuscleRequest):
    operation: Literal["muscle.search", "muscle.resolve", "muscle.describe"]
    query: str = Field(default="", max_length=80)
    side: Literal["left", "right", "unknown"] | None = None
    display_node: Node | None = None
    inventory: Literal["native", "display"] = "native"
    region: Literal["torso", "shoulder", "arm_hand", "pelvis", "leg_foot", "spine", "unknown"] | None = None
    status: Literal["mapped", "candidate", "geometry_only", "unmapped", "missing_asset", "conflict"] | None = None
    brief: bool = False
    offset: int = Field(default=0, ge=0, le=700)
    limit: int = Field(default=20, ge=1, le=40)

    @model_validator(mode="after")
    def check_selector(self):
        if self.display_node is not None and (self.query or self.offset or self.status or self.region):
            raise ValueError("display node is a complete selector")
        return self


class MuscleSeries(MuscleRequest):
    operation: Literal["muscle.timeseries"]
    metric: Metric = "activation"
    actuator_ids: list[Index] = Field(default_factory=list, max_length=16)
    group_id: Group | None = None
    start_s: FiniteFloat | None = Field(default=None, ge=0, le=3600)
    end_s: FiniteFloat | None = Field(default=None, ge=0, le=3600)
    offset: int = Field(default=0, ge=0, le=400)
    limit: int = Field(default=120, ge=1, le=120)
    stride: int = Field(default=1, ge=1, le=20)
    phase_summary: bool = False

    @model_validator(mode="after")
    def check_series(self):
        if bool(self.actuator_ids) == bool(self.group_id) or len(set(self.actuator_ids)) != len(self.actuator_ids):
            raise ValueError("choose a single reviewed group or distinct native IDs")
        return self


class MuscleView(MuscleModel):
    mapping_revision_sha256: Sha
    display_node: Node | None = None
    metric: Metric = "activation"
    actuator_id: Index | None = None
    overlay: bool = False
    isolate: bool = False
    opacity: FiniteFloat = Field(default=1, ge=0.1, le=1)
    opacity_scope: Literal["selection", "surface", "source"] = "selection"

    @model_validator(mode="after")
    def check_identity(self):
        if self.display_node is None and self.actuator_id is None:
            raise ValueError("choose a native actuator or a display node")
        return self


class MuscleSelect(MuscleRequest):
    operation: Literal["muscle.select"]
    motion_sha256: Sha
    state_index: int = Field(strict=True, ge=0, le=400)
    selection: MuscleView
    publish: bool = False
    if_match: Sha | None = None


class MuscleSelection(MuscleRequest):
    operation: Literal["muscle.selection"]


class MuscleRegistration(MuscleRequest):
    operation: Literal["muscle.registration"]
    motion_sha256: Sha
    mapping_revision_sha256: Sha
    state_index: int = Field(strict=True, ge=0, le=400)
    actuator_id: Index | None = None
    display_node: Node | None = None
    group_id: Group | None = None
    side: Literal["left", "right", "unknown"] | None = None
    offset: int = Field(default=0, strict=True, ge=0, le=700)
    limit: int = Field(default=8, strict=True, ge=1, le=16)
    evidence_frame: Literal["mujoco_world_m"] | None = None
    evidence_revision_sha256: Sha | None = None

    @model_validator(mode="after")
    def check_selector(self):
        if sum(v is not None for v in (self.actuator_id, self.display_node, self.group_id)) != 1:
            raise ValueError("choose one native actuator, display node or reviewed group")
        if self.evidence_revision_sha256 is not None and self.evidence_frame is None:
            raise ValueError("evidence revision requires a coordinate frame")
        return self


MUSCLE_REQUESTS = (MuscleSearch, MuscleSeries, MuscleSelect, MuscleSelection, MuscleRegistration)
