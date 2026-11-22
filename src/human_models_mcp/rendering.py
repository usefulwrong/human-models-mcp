"""Typed render requests and durable artifacts; no Blender imports or container control."""

import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .evidence import code_sha256
from .registry import home
from .results import error, get_run, run_dir

PROFILES = {
    "preview": {"width": 480, "height": 270, "samples": 4, "device": "cpu"},
    "scientific": {"width": 960, "height": 540, "samples": 16, "device": "auto", "frames": 51, "fps": 15},
    "cinematic": {"width": 1280, "height": 720, "samples": 32, "device": "auto", "frames": 51, "fps": 15},
}
LAYERS = {
    "pectoralis_atlas": "BodyParts3D right clavicular pectoralis major surface, illustrated with two-bone skinning.",
    "rectus_atlas": "Bilateral Z-Anatomy rectus abdominis surfaces with illustrative saved-site registration.",
    "native_geometry": "Native visible model geoms; collision coverage and anatomy are incomplete.",
    "bones": "Native source skeletal meshes, not a new atlas or anatomical completeness claim.",
    "muscle_paths": "Selected native tendon paths, not volumetric muscles or tissue deformation.",
    "arm_muscles": "All bilateral source arm/shoulder muscle paths, including forearm and wrist actuators.",
    "pectoral_muscles": "Six bilateral native PECM1/2/3 paths with saved activation; no inferred muscle volumes.",
    "lumbar_muscles": "All source lumbar/spinal stabilizer, psoas and latissimus paths.",
    "abdominal_muscles": "All source rectus, oblique and transverse abdominal paths.",
    "hand_tendons": "All 48 native extrinsic hand/wrist musculotendon paths; not separately deformable tendon tissue.",
    "hand_contacts": "Actual mechanical hand pads and per-hand floor forces and ground moments about the wrists.",
    "joint_axes": "Compiled world joint axes, explanatory colors; model ranges are not human norms.",
    "contact_forces": "Saved ground reaction and explicit support wrench; arrow scale m/N, not tissue pressure.",
    "center_of_mass": "Native mass-weighted whole-model COM, in metres.",
    "applied_moments": "Recorded generalized elbow torque or external pelvis moment pseudovector [N*m]; not biological joint reaction.",
}
SUPPORTED = {"elbow_tracking", "loaded_elbow", "standing_contact_probe", "assisted_stance", "pushup", "pushup_palms", "pushup_knuckles"}
RECIPES = {
    "pushup_scientific": {"profile": "scientific", "layers": ["bones", "joint_axes", "contact_forces", "center_of_mass"]},
    "pushup_muscle_paths": {"profile": "scientific", "layers": ["bones", "muscle_paths"]},
    "pushup_anatomy": {"profile": "scientific", "layers": ["bones", "pectoralis_atlas"], "camera_view": "chest"},
    "pushup_rectus": {"profile": "scientific", "layers": ["bones", "rectus_atlas"], "camera_view": "abdomen"},
    "pushup_cinematic": {"profile": "cinematic", "layers": ["bones", "muscle_paths"]},
}
ATLAS_LAYERS = {"pectoralis_atlas", "rectus_atlas"}
MAX_CHUNK = 256 * 1024
MAX_FILE = 128 * 1024 * 1024


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    width: int = Field(default=480, ge=320, le=1920)
    height: int = Field(default=270, ge=180, le=1080)
    samples: int = Field(default=4, ge=1, le=128)
    frames: int = Field(default=21, ge=3, le=101)
    fps: int = Field(default=6, ge=1, le=30)
    device: Literal["cpu", "gpu", "auto"] = "cpu"
    camera_view: Literal["full_body", "hands", "lumbar", "abdomen", "chest"] = "full_body"
    timeout_s: int = Field(default=600, ge=30, le=900)

    @model_validator(mode="after")
    def budget(self):
        if self.width % 2 or self.height % 2:
            raise ValueError("MP4 dimensions must be even")
        if self.width * self.height * self.frames * self.samples > 4_000_000_000:
            raise ValueError("render sample budget exceeds 4 billion pixel-samples")
        return self


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def render_lock_digests():
    return {name: digest(path) for name in ("renderer.lock.json", "requirements-render.lock")
            if (path := home() / name).is_file()}


def write_json(path, value):
    temporary = path.with_name("." + path.name + "." + str(uuid4()))
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def queue_root():
    root = home() / "render_jobs"
    if root.is_symlink():
        raise ValueError("render queue must not be a symlink")
    root.mkdir(exist_ok=True)
    return root


def job_dir(job_id):
    if str(UUID(job_id)) != job_id:
        raise ValueError("job_id must be a canonical UUID")
    root = queue_root()
    path = root / job_id
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("invalid render job location")
    return path


def read_job(job_id):
    path = job_dir(job_id) / "job.json"
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("invalid job record")
    result = json.loads(path.read_text())
    if not isinstance(result, dict) or result.get("job_id") != job_id:
        raise ValueError("invalid job record shape")
    return result


def list_render_profiles():
    source_registry = home() / "visual_sources.json"
    registry = (
        json.loads(source_registry.read_text())
        if source_registry.is_file()
        else {"sources": [], "status": "registry_not_installed"}
    )
    return {
        "profiles": PROFILES,
        "recipes": RECIPES,
        "reference_overlay": "Local comparison CLI for licensed Fit3D data; absent from shared render artifacts.",
        "anatomical_sources": registry,
        "layers": LAYERS,
        "supported_scenarios": sorted(SUPPORTED),
        "unsupported_layers": {
            "wrist_ligaments": "no discrete source wrist ligament geometry or material model; generalized constraints are not ligaments",
            "atlas_reference": "registration_unverified; external source mapping and redistribution not approved",
            "skin": "no registered skin mesh/deformation",
            "muscle_volumes": "tendon paths are not muscle volumes",
            "internal_organs": "no registered organ or physiological model",
        },
        "limits": {
            "options_schema": RenderOptions.model_json_schema(),
            "concurrent_jobs": 1,
            "maximum_stored_jobs": 128,
            "maximum_artifact_bytes": MAX_FILE,
            "maximum_chunk_bytes": MAX_CHUNK,
        },
        "method": "restore existing integration states; no mj_step or controller execution",
        "worker": "separate optional Docker Blender Cycles service, host-started; offline runtime",
        "evidence": "Geometry/time equality checks, not human accuracy, tissue mechanics or clinical validation.",
    }


def snapshot(run, destination):
    source = run_dir(run["run_id"])
    manifest = source / "manifest.json"
    if manifest.is_symlink() or json.loads(manifest.read_text()) != run:
        raise ValueError("source manifest changed during submission")
    destination.mkdir()
    shutil.copyfile(manifest, destination / "manifest.json")
    files = {"manifest.json": digest(manifest)}
    selected = {
        "trajectory.npz",
        "trajectory_metadata.json",
        "series.csv",
        "model_recipe.json",
        "initial_conditions.json",
        "contact_map.json",
        "support.json",
        "contacts.json",
        "validation.json",
        "bibliography.json",
        "environment.json",
        "actuators.json",
        "muscle_ranking.json",
        "summary.json",
        "reference.npz",
        "palm_reference_input.json",
        "wrists.json",
        "support_stationarity.json",
        "pectorals.csv",
        "pectorals.json",
    }
    selected |= {k for k in run["artifacts"] if re.fullmatch(r"contacts_[0-9]{3}\.json", k)}
    selected |= {k for k in run["artifacts"] if re.fullmatch(r"muscles_[0-9]{3}\.npz", k)}
    total = 0
    for name in sorted(selected & run["artifacts"].keys()):
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("invalid source artifact: " + name)
        if digest(path) != run["artifacts"][name]["sha256"]:
            raise ValueError("source checksum mismatch: " + name)
        total += path.stat().st_size
        if total > 32 * 1024 * 1024:
            raise ValueError("source snapshot exceeds 32 MiB")
        target = destination / name
        shutil.copyfile(path, target)
        copied = digest(target)
        if copied != run["artifacts"][name]["sha256"]:
            raise ValueError("source changed while copying: " + name)
        files[name] = copied
    if not {"trajectory.npz", "series.csv"} <= files.keys():
        raise ValueError("saved trajectory and numeric series required")
    return files


def render_result(run_id, profile=None, layers=None, options=None, idempotency_key=None, recipe=None):
    temporary = None
    try:
        if recipe is not None:
            if recipe not in RECIPES:
                return error("unsupported", "unknown render recipe")
            if layers is not None:
                return error("invalid_input", "select either a recipe or explicit layers")
            layers = RECIPES[recipe]["layers"]
            profile = RECIPES[recipe]["profile"] if profile is None else profile
        profile = "preview" if profile is None else profile
        if profile not in PROFILES:
            return error("unsupported", "unknown render profile")
        selected = layers if layers is not None else ["bones", "muscle_paths", "joint_axes"]
        if (
            not isinstance(selected, list)
            or not selected
            or len(selected) > len(LAYERS)
            or any(not isinstance(x, str) for x in selected)
        ):
            return error("invalid_input", "layers must be a nonempty list of supported identifiers")
        if set(selected) - LAYERS.keys():
            return error(
                "unsupported",
                "unavailable layers: "
                + ", ".join(sorted(set(selected) - LAYERS.keys()))
                + "; external anatomy registration is unverified",
            )
        camera = RECIPES.get(recipe, {}).get("camera_view", "full_body")
        settings = RenderOptions.model_validate({**PROFILES[profile], "camera_view": camera, **(options or {})}).model_dump()
        run = get_run(run_id)
        if run.get("status") != "computed":
            return error("invalid_input", "rendering requires an existing computed run")
        if run["scenario_id"] not in SUPPORTED:
            return error("unsupported", "this scenario has no supported saved dynamic trajectory transfer")
        duration = run.get("execution", {}).get("simulation_time_s")
        if recipe and duration and "fps" not in (options or {}):
            settings["fps"] = max(1, min(30, round((settings["frames"] - 1) / duration)))
        if (recipe is not None or ATLAS_LAYERS.intersection(selected)) and not run["scenario_id"].startswith("pushup"):
            return error("unsupported", "pushup recipes and atlas require a pushup scenario")
        if ATLAS_LAYERS <= set(selected):
            return error("unsupported", "select one atlas region per view")
        atlas = None
        if "pectoralis_atlas" in selected:
            from .atlas import atlas_inputs, atlas_lock_digest
            try:
                atlas = atlas_inputs()
            except (OSError, ValueError) as exc:
                return error("unsupported", "Atlas input unavailable: " + str(exc))
        if "rectus_atlas" in selected:
            from .atlas import atlas_lock_digest
            from .rectus import rectus_inputs
            try:
                atlas = rectus_inputs()
            except (OSError, ValueError) as exc:
                return error("unsupported", "Rectus atlas input unavailable: " + str(exc))
        if settings["frames"] > run.get("execution", {}).get("integration_steps", 0) + 1:
            return error("invalid_input", "requested frames exceed the saved state count")
        if "contact_forces" in selected and "contacts" not in run["outputs"]:
            return error("unsupported", "source experiment has no floor-contact measurement")
        if "hand_contacts" in selected and "wrists.json" not in run["artifacts"]:
            return error("unsupported", "hand detail layer requires a palms/knuckles experiment with saved wrist measurements")
        if settings["camera_view"] == "hands" and "wrists.json" not in run["artifacts"]:
            return error("unsupported", "hand camera requires saved wrist measurements")
        if settings["camera_view"] == "chest" and "pectorals.csv" not in run["artifacts"] and "pectoralis_atlas" not in selected:
            return error("unsupported", "chest camera requires an experiment with saved bilateral pectoral measurements")
        if set(selected) & {"arm_muscles", "lumbar_muscles", "abdominal_muscles", "hand_tendons", "pectoral_muscles"} and run["model"]["id"] != "ms_human_700":
            return error("unsupported", "regional upper-body paths require the full primary model")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128
        ):
            return error("invalid_input", "idempotency_key must be 1–128 characters")
        request = {"run_id": run_id, "profile": profile, "layers": sorted(set(selected)), "options": settings}
        if recipe is not None or atlas:
            request.update(recipe=recipe, render_code_sha256=code_sha256(),
                           render_lock_sha256=render_lock_digests(),
                           source_manifest_sha256=digest(run_dir(run_id) / "manifest.json"))
        if atlas:
            request["atlas_lock_sha256"] = atlas_lock_digest(atlas)
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        root = queue_root()
        with (root / ".submit.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            key = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else None
            jobs = sorted(root.glob("*/job.json"))
            if key or recipe is not None:
                for path in jobs:
                    previous = read_job(path.parent.name)
                    if key and previous.get("idempotency_key_sha256") == key:
                        return (
                            get_render_job(previous["job_id"])
                            if previous["request_sha256"] == request_hash
                            else error("invalid_input", "idempotency key has different render parameters")
                        )
                    if not key and previous["request_sha256"] == request_hash:
                        cached = get_render_job(previous["job_id"])
                        if cached["status"] in {"queued", "running", "completed"}:
                            for name, expected in cached["source_files"].items():
                                if name not in run["artifacts"] and name != "manifest.json":
                                    continue
                                current = run_dir(run_id) / name
                                if current.is_symlink() or not current.is_file() or current.stat().st_size > 2 * 1024 * 1024 or digest(current) != expected:
                                    raise ValueError("source checksum mismatch: " + name)
                            return cached
            if len(jobs) >= 128:
                return error(
                    "resource_limit", "render store full; operator must archive/remove selected own jobs"
                )
            job_id = str(uuid4())
            temporary = root / (".submit-" + job_id)
            temporary.mkdir()
            files = snapshot(run, temporary / "input")
            atlas_files = {}
            if atlas:
                from .atlas import atlas_cache, verify_asset
                for name, asset in atlas["files"].items():
                    dest = temporary / "input" / name
                    shutil.copyfile(atlas_cache() / name, dest)
                    verify_asset(dest, asset)
                    atlas_files[name] = asset["sha256"]
            record = {
                "job_id": job_id,
                "status": "queued",
                "created_at": now(),
                "request": request,
                "request_sha256": request_hash,
                "idempotency_key_sha256": key,
                "source_files": files,
                **({"atlas_source_files": atlas_files} if atlas_files else {}),
                "source_run_status": "computed",
                "artifacts": {},
                "progress": {"phase": "queued"},
                "scientific": {
                    "validation_level": "unvalidated",
                    "limitations": run["scientific"]["limitations"],
                    "acceptance": run["scientific"].get("acceptance", {}),
                    "anatomical_registration": "native_model_only; external registration_unverified",
                },
            }
            write_json(temporary / "job.json", record)
            temporary.rename(root / job_id)
            temporary = None
            return record
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        return error("invalid_input", str(exc)[:1000])
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def get_render_job(job_id):
    try:
        record = read_job(job_id)
        if record["status"] == "running":
            with (queue_root() / ".worker.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return record
                record = read_job(job_id)
                if record["status"] != "running":
                    return record
                record.update(
                    status="failed",
                    completed_at=now(),
                    error={
                        "code": "interrupted",
                        "message": "No render worker owns this running job; partial files retained.",
                    },
                )
                write_json(job_dir(job_id) / "job.json", record)
        return record
    except (OSError, ValueError, KeyError):
        return error("invalid_input", "unknown or invalid job_id")


def artifact_metadata(path):
    size = path.stat().st_size
    if path.is_symlink() or not 0 < size <= MAX_FILE:
        raise ValueError("render artifact is empty or exceeds 128 MiB")
    return {
        "sha256": digest(path),
        "bytes": size,
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }


def get_render_artifact(job_id, artifact_id, offset=0, length=MAX_CHUNK):
    try:
        if type(offset) is not int or type(length) is not int or offset < 0 or not 1 <= length <= MAX_CHUNK:
            return error("invalid_input", "offset >= 0, chunk length 1–262144 bytes required")
        record = get_render_job(job_id)
        meta = record.get("artifacts", {}).get(artifact_id)
        if not meta or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9]+", artifact_id):
            return error("invalid_input", "artifact_id is not in this render manifest")
        path = job_dir(job_id) / "artifacts" / artifact_id
        if (
            path.parent.is_symlink()
            or path.is_symlink()
            or path.resolve().parent != (job_dir(job_id) / "artifacts").resolve()
        ):
            return error("invalid_input", "invalid artifact location")
        if path.stat().st_size != meta["bytes"] or digest(path) != meta["sha256"]:
            return error("integrity_error", "render artifact changed or is missing")
        if offset > meta["bytes"]:
            return error("invalid_input", "offset beyond end of artifact")
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        return {
            "status": "ok",
            "artifact_id": artifact_id,
            **meta,
            "offset": offset,
            "next_offset": offset + len(data),
            "eof": offset + len(data) == meta["bytes"],
            "encoding": "base64",
            "data": base64.b64encode(data).decode(),
            "chunk_sha256": hashlib.sha256(data).hexdigest(),
        }
    except (OSError, ValueError, TypeError):
        return error("invalid_input", "unknown or invalid render artifact")
