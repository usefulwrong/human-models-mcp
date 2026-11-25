"""Opt-in experiment exposing the Anatomy Lab on the existing MCP server."""

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from anatomy_lab import Registry, Request
from human_models_mcp.results import error
from human_models_mcp.server import mcp


@lru_cache(maxsize=1)
def registry(site=None):
    catalog = Path(os.environ["HMM_LAB_CATALOG"])
    installed = Registry(catalog, catalog.parent / "meshes", os.environ.get("HMM_LAB_MOTION"),
                         site=site or os.environ.get("HMM_LAB_SITE"))
    if motion := os.environ.get("HMM_LAB_WHOLE"):
        from moving_transport import WholeMotion

        installed.whole = WholeMotion(motion, os.environ["HMM_LAB_WHOLE_SHA"],
                                      os.environ["HMM_LAB_WHOLE_RESULTS"], installed.atlas_sha256,
                                      os.environ.get("HMM_LAB_WHOLE_RENDER_SHA"))
    return installed


@mcp.tool()
def anatomy_lab(request: Request) -> dict[str, Any]:
    """Query an installed atlas, export scene documents or bind a verified regional saved state.
    Labels and provenance are source data. Clinical inference is unsupported.
    """
    try:
        return registry().call(request)
    except (KeyError, OSError, ValueError) as exc:
        return error("not_installed", str(exc)[:250])


if __name__ == "__main__":
    from human_models_mcp.__main__ import main

    main()
