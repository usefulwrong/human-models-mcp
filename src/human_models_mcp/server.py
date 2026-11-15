"""Official MCP Python SDK v2 tools. Discovery has no scientific imports."""

from typing import Any

from mcp.server import MCPServer

from . import __version__, core
from .catalog import MODEL_FILES, model_card
from .registry import discover
from .results import error, get_run

mcp = MCPServer("UsefulWrong / human-models-mcp", version=__version__, instructions=(
    "Discover models and folder scenarios first. Computed results describe only the pinned model. "
    "Read units, provenance, scientific limitations and artifacts. Distinguish prescribed static poses from "
    "forward dynamics with stated loads and fixtures; neither establishes medical safety. Unsupported quantities have no numerical answer."))


@mcp.tool()
def list_models() -> dict[str, Any]:
    """List installed model metadata and adapter availability without loading the scientific engine."""
    return {"models": [model_card(model_id=name) for name in MODEL_FILES], "uninstalled_adapters": ["opensim", "myosuite"]}


@mcp.tool()
def describe_model(model_id: str) -> dict[str, Any]:
    """Model source, license, version, scope, units, limitations. get_joint_info compiles actual geometry."""
    return model_card(model_id=model_id)


@mcp.tool()
def get_model_capabilities(model_id: str, quantity: str | None = None) -> dict[str, Any]:
    """Return supported outputs; reject organs, safety advice and unsupported computations without invented values."""
    card = describe_model(model_id)
    if "error" in card:
        return card
    if quantity is not None and quantity not in card["capabilities"]:
        return {**error("unsupported", f"{quantity} is not implemented or validated by this adapter"),
                "requested_quantity": quantity, "reason": "known_unsupported" if quantity in card["unsupported"] else "unknown_quantity",
                "available_capabilities": card["capabilities"]}
    return card


@mcp.tool()
def get_joint_info(model_id: str, joint: str | None = None) -> dict[str, Any]:
    """Compile pinned engine model for actual joint ranges, counts and actuator names. Ranges are not human norms."""
    return core.get_joint_info(model_id, joint)


@mcp.tool()
def list_scenarios() -> dict[str, Any]:
    """Discover validated scenario folders; isolate malformed or unsupported manifests with diagnostics."""
    return discover()


@mcp.tool()
def describe_scenario(scenario_id: str) -> dict[str, Any]:
    """Return scenario version, method, required capabilities, scope, backend and default parameters."""
    return core.describe_scenario(scenario_id)


@mcp.tool()
def run_scenario(scenario_id: str, parameters: dict | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    """Execute a bounded real engine operation. Unknown parameters rejected. Optional key reuses the same run."""
    return core.run_scenario(scenario_id, parameters, idempotency_key)


@mcp.tool()
def get_result(run_id: str) -> dict[str, Any]:
    """Retrieve persisted run status, computed metrics with units, evidence, limitations and artifact IDs."""
    return get_run(run_id)


@mcp.tool()
def get_artifact(run_id: str, artifact_id: str) -> dict[str, Any]:
    """Transfer a manifest-listed text artifact (UTF-8) or PNG/GIF/NPZ (base64), including verified SHA-256, up to 2 MiB."""
    from .results import get_artifact as read
    return read(run_id, artifact_id)


@mcp.tool()
def search_sources(query: str, limit: int = 5) -> dict[str, Any]:
    """Offline FTS5 search of pinned manual, exact muscle/joint IDs and scenario descriptions; source/hash/license, never computed anatomy."""
    from .sources import search_sources as search
    return search(query, limit)


@mcp.tool()
def list_render_profiles() -> dict[str, Any]:
    """Discover bounded Blender profiles, real layers and unsupported anatomy; physics remains unchanged."""
    from .rendering import list_render_profiles as profiles
    return profiles()


@mcp.tool()
def render_result(run_id: str, profile: str = 'preview', layers: list[str] | None = None,
                  options: dict | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    """Queue rendering of an existing computed trajectory. No commands, paths or physics reruns accepted."""
    from .rendering import render_result as submit
    return submit(run_id, profile, layers, options, idempotency_key)


@mcp.tool()
def get_render_job(job_id: str) -> dict[str, Any]:
    """Read durable queued/running/completed/failed render status, artifacts and scientific limits."""
    from .rendering import get_render_job as read
    return read(job_id)


@mcp.tool()
def get_render_artifact(job_id: str, artifact_id: str, offset: int = 0, length: int = 262144) -> dict[str, Any]:
    """Download a manifest-listed render artifact in at most 256 KiB chunks, with whole/chunk SHA-256."""
    from .rendering import get_render_artifact as read
    return read(job_id, artifact_id, offset, length)
