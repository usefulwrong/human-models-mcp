"""Run a bounded experiment and queue named views on its saved states."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .core import run_scenario
from .evidence import get_evidence
from .rendering import RenderOptions, render_result
from .results import error

Recipe = Literal["pushup_scientific", "pushup_muscle_paths", "pushup_anatomy", "pushup_rectus", "pushup_cinematic"]


class ResearchViews(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipes: list[Recipe] = Field(default_factory=lambda: ["pushup_scientific"], max_length=5)
    options: RenderOptions | None = None


class ResearchRequest(ResearchViews):
    scenario_id: Literal["pushup", "pushup_palms", "pushup_knuckles"] = "pushup_palms"
    parameters: dict = Field(default_factory=dict, description="Overrides validated by the named scenario.")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


def run_research(request: ResearchRequest) -> dict:
    """Compute once per supplied key, verify evidence inputs, then submit recipe jobs."""
    if len(set(request.recipes)) != len(request.recipes):
        return error("invalid_input", "select each recipe at most once")
    run = run_scenario(request.scenario_id, request.parameters, request.idempotency_key)
    if "scientific" not in run:
        return run
    evidence = get_evidence(run["run_id"])
    if "error" in evidence:
        return {"run_id": run["run_id"], **evidence}
    options = request.options.model_dump(exclude_unset=True) if request.options else None
    jobs = {}
    if run["status"] == "computed":
        for recipe in request.recipes:
            job = render_result(run["run_id"], options=options, recipe=recipe)
            jobs[recipe] = {key: job[key] for key in ("status", "job_id", "error") if key in job}
    return {
        "status": ("partial" if any("error" in job for job in jobs.values()) else
                   "submitted" if jobs else run["status"]),
        "run_id": run["run_id"],
        **{key: evidence[key] for key in ("computed_status", "control_mode", "acceptance", "numeric_checks",
                                         "human_validation_status", "human_safety_status")},
        "scientific_artifact_ids": list(run.get("artifacts", {})),
        "evidence_query": {"run_id": run["run_id"], "claim_id": "all"},
        "render_jobs": jobs,
        **({"error": run["error"]} if "error" in run else {}),
    }
