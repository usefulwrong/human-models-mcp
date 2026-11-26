"""Bounded read-only transport for an operator-installed whole-body MotionScene."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

from anatomy_lab import canonical, digest, read_bounded

SCHEMA = "hmm.anatomy.motion/1"
ARTIFACTS = {"motion.glb": 32 << 20, "coverage.json": 4 << 20, "scene.blend": 256 << 20,
             "assisted-pushup.mp4": 50 << 20}


class WholeMotion:
    def __init__(self, scene_path, scene_sha, run_root, atlas_sha, render_sha=None):
        self.path = Path(scene_path)
        self.sha = scene_sha
        self.run_root = Path(run_root)
        self.atlas_sha = atlas_sha
        self.render_sha = render_sha

    def verified(self):
        raw = read_bounded(self.path, 1 << 20)
        if digest(raw) != self.sha:
            raise ValueError("installed MotionScene SHA-256 differs")
        scene = json.loads(raw)
        run = self.run_root / scene["run_id"]
        if (run.is_symlink() or run.resolve().parent != self.run_root.resolve() or scene["schema_version"] != SCHEMA
                or scene["catalog_sha256"] != self.atlas_sha):
            raise ValueError("MotionScene schema, catalog SHA-256 or run location differs")
        manifest = read_bounded(run / "manifest.json", 1 << 20)
        trajectory = read_bounded(run / "trajectory.npz", 8 << 20)
        if (digest(manifest) != scene["source_manifest_sha256"]
                or digest(trajectory) != scene["trajectory_sha256"]):
            raise ValueError("saved source manifest or trajectory SHA-256 differs")
        return scene

    @contextmanager
    def open_artifact(self, name, scene=None):
        scene = scene or self.verified()
        limit = ARTIFACTS[name]
        path = self.path.parent
        if name in scene["artifacts"]:
            metadata = scene["artifacts"][name]
        elif self.render_sha and name in {"scene.blend", "assisted-pushup.mp4"}:
            raw = read_bounded(path / "render" / "receipt.json", 32 << 10)
            receipt = json.loads(raw)
            if digest(raw) != self.render_sha or receipt["motion_sha256"] != self.sha:
                raise ValueError("renderer receipt SHA-256 or motion identity differs")
            path = path / "render"
            if path.is_symlink():
                raise ValueError("invalid render directory")
            metadata = receipt["artifacts"][name]
        else:
            raise LookupError("artifact is not installed")
        target = path / name
        if target.is_symlink() or not target.is_file() or not 0 < metadata["bytes"] <= limit:
            raise ValueError("invalid motion artifact path or size")
        with target.open("rb") as stream:
            if (os.fstat(stream.fileno()).st_size != metadata["bytes"]
                    or hashlib.file_digest(stream, "sha256").hexdigest() != metadata["sha256"]):
                raise ValueError("motion artifact size or SHA-256 differs")
            stream.seek(0)
            yield stream, metadata

    def call(self, request):
        scene = self.verified()
        if request.operation == "whole.discover":
            return {"status": "ok", "runs": [{k: scene[k] for k in ("run_id", "scenario_id", "control")}]}
        if str(request.run_id) != scene["run_id"]:
            raise LookupError("no whole-body animation for that run")
        if request.operation == "whole.open":
            return {"status": "ok", "motion_sha256": self.sha, "motion": scene}
        if request.operation == "whole.contact":
            from human_models_mcp.contact_results import get_contact
            from human_models_mcp.results import error

            if "contact" not in scene:
                return error("unsupported", "no experimental contact evidence for this motion")
            result = get_contact(scene["run_id"], request.part, sample=request.sample)
            if result["status"] == "ok":
                frame = scene["frames"][request.sample]
                if (result["state_sha256"] != frame["state_sha256"] or result["time_s"] != frame["frame_time"]
                        or result["scientific_quantity"]["sources_sha256"]["contact_manifest.json"]
                        != scene["contact"]["manifest_sha256"]):
                    raise ValueError("contact receipt differs from the installed MotionScene")
            return result
        if request.operation == "whole.artifact":
            with self.open_artifact(request.artifact_id, scene) as (_, identity):
                return {"status": "ok", **identity, "artifact_id": request.artifact_id,
                        "url": f"/api/whole/{request.artifact_id}/{identity['sha256']}"}
        chosen = request.view
        if chosen.motion_sha256 != self.sha:
            raise ValueError("saved view belongs to a different MotionScene")
        if chosen.state_index not in {f["state_index"] for f in scene["frames"]}:
            raise ValueError("exact source state is unavailable")
        if (len(set(chosen.layers)) != len(chosen.layers)
                or any(not scene["layers"][layer]["available"] for layer in chosen.layers)
                or chosen.camera.position == chosen.camera.target):
            raise ValueError("invalid moving layers or camera")
        view = chosen.model_dump(mode="json")
        return {"status": "ok", "view": view, "view_sha256": digest(canonical(view))}
