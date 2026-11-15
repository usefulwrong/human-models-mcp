"""Bounded artifact access through identifiers, never user-supplied paths."""

import base64
import fcntl
import hashlib
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone

from .registry import home

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def error(code: str, message: str) -> dict:
    return {"status": code, "error": {"code": code, "message": message}}


def store() -> Path:
    return home() / "results"


def run_dir(run_id: str) -> Path:
    if str(UUID(run_id)) != run_id:
        raise ValueError("run_id must be a canonical UUID")
    path = store() / run_id
    if path.is_symlink() or path.resolve().parent != store().resolve():
        raise ValueError("invalid run location")
    return path


def get_run(run_id: str) -> dict:
    try:
        p = run_dir(run_id) / "manifest.json"
        if p.is_symlink() or p.stat().st_size > MAX_ARTIFACT_BYTES:
            return error("invalid_input", "invalid manifest")
        manifest = json.loads(p.read_text())
        if not isinstance(manifest, dict):
            return error("invalid_input", "invalid manifest shape")
        if manifest.get("status") == "running":
            with (store() / ".executor.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return manifest
                try:
                    manifest = interrupt_run(p, manifest)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        return manifest
    except (OSError, ValueError):
        return error("invalid_input", "unknown or invalid run_id")


def interrupt_run(path: Path, manifest: dict) -> dict:
    """Called only while holding the executor lock; retain all partial files."""
    if not isinstance(manifest, dict):
        raise ValueError("invalid manifest shape")
    if manifest.get("status") != "running":
        return manifest
    manifest["status"] = "failed"
    manifest.setdefault("execution", {})["result_status"] = "failed"
    manifest.setdefault("scientific", {})["validation_level"] = "unvalidated"
    manifest["error"] = {"code": "interrupted", "message": "No executor owns this running record; execution was interrupted. Partial files are retained."}
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
    return manifest


def get_artifact(run_id: str, artifact_id: str) -> dict:
    manifest = get_run(run_id)
    artifacts = manifest.get("artifacts", {})
    if artifact_id not in artifacts:
        return error("invalid_input", "artifact_id is not present in this run manifest")
    p = run_dir(run_id) / artifact_id
    if p.is_symlink() or p.resolve().parent != run_dir(run_id).resolve():
        return error("invalid_input", "invalid artifact location")
    if not p.is_file():
        return error("integrity_error", "manifest-listed artifact is missing")
    if p.stat().st_size > MAX_ARTIFACT_BYTES:
        return error("resource_limit", "artifact exceeds 2 MiB")
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != artifacts[artifact_id]["sha256"]:
        return error("integrity_error", "artifact hash differs from manifest")
    binary = artifacts[artifact_id]["mime_type"] not in ("application/json", "text/csv", "text/plain")
    return {"status": "ok", "artifact_id": artifact_id, "sha256": digest,
            "mime_type": artifacts[artifact_id]["mime_type"], "encoding": "base64" if binary else "utf-8",
            "data": base64.b64encode(data).decode() if binary else data.decode()}
