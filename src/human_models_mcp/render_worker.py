"""One durable render worker. Owns bounded Blender processes; never controls Docker."""

import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
import tempfile
import zipfile

from .registry import home
from .runtime.locking import file_lock
from .runtime.processes import managed_process
from .runtime.paths import flat_name, is_link
from .evidence import code_sha256, evidence_context
from .rendering import (
    LAYERS,
    MAX_FILE,
    RenderOptions,
    artifact_metadata,
    digest,
    job_dir,
    now,
    queue_root,
    read_job,
    render_lock_digests,
    write_json,
)


def source_integrity(folder, record):
    if is_link(folder / "input"):
        raise ValueError("symlinked render input")
    for name, expected in (record["source_files"] | record.get("atlas_source_files", {})).items():
        if not flat_name(name):
            raise ValueError("invalid source filename")
        path = folder / "input" / name
        if is_link(path) or path.stat().st_size > 2 * 1024 * 1024 or digest(path) != expected:
            raise ValueError("immutable input hash mismatch: " + name)


def gpu_memory():
    try:
        value = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return max(int(v.strip()) for v in value.splitlines())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def blender(folder, options, device_override=None):
    log = folder / "blender.log"
    env = dict(os.environ)
    for name, subdirectory in (("BLENDER_USER_CONFIG", "blender-config"),
                               ("CUDA_CACHE_PATH", "cuda-cache"), ("XDG_CACHE_HOME", ".cache")):
        env.setdefault(name, str(Path(tempfile.gettempdir()) / subdirectory))
    if device_override:
        env["HMM_BLENDER_DEVICE"] = device_override
    command = [
        os.environ.get("BLENDER_BIN", "blender.exe" if os.name == "nt" else "/opt/blender/blender"),
        "-b",
        "--factory-startup",
        "--threads",
        "2",
        "--python-exit-code",
        "1",
        "--python",
        str(Path(__file__).with_name("blender_scene.py")),
        "--",
        str(folder),
    ]
    memory = []
    started = time.monotonic()
    with log.open("ab") as stream, managed_process(
        command, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env=env, memory=8 * 1024**3, linux_group=True,
    ) as process:
        while process.poll() is None:
            if time.monotonic() - started > options["timeout_s"]:
                raise TimeoutError("Blender wall time exceeded")
            m = gpu_memory() if options["device"] != "cpu" and device_override != "cpu" else None
            if m is not None:
                memory.append(m)
            time.sleep(0.5)
    if process.returncode:
        text = log.read_text(errors="replace", encoding="utf-8")[-5000:]
        raise RuntimeError("Blender exit " + str(process.returncode) + ": " + text)
    return {
        "seconds": time.monotonic() - started,
        "peak_device_memory_used_MiB": max(memory) if memory else None,
        "memory_measurement": "Device-wide nvidia-smi samples at approximately 0.5 s, includes other GPU use; not process-exclusive allocation",
    }


def package_media(folder, expected):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image, ImageDraw

    work, out = folder / "work", folder / "artifacts"
    frames = []
    settings = expected["request"]["options"]
    pushup = expected.get("pushup", expected["scenario_id"] == "pushup")
    hand_view = pushup and settings.get("camera_view") == "hands"
    chest_view = pushup and settings.get("camera_view") == "chest"
    regional_view = pushup and settings.get("camera_view") in ("lumbar", "abdomen", "chest")
    contact = expected["model"]["id"] == "ms_human_700_locomotion" or pushup
    with (folder / "input/series.csv").open() as stream:
        trace = list(csv.DictReader(stream))
    times = [float(r["time_s"]) for r in trace]
    key = "grf_z_N" if contact else "angle_rad"
    label = "GRF z [N]" if contact else "Elbow angle [rad]"
    values = [float(r[key]) for r in trace]
    figure, axes = plt.subplots(1, 2 if pushup else 1, figsize=(10, 1.6) if pushup else (5, 2), dpi=100, layout="constrained")
    axis = axes[0] if pushup else axes
    axis.plot(times, values, color="#006c84", label=label)
    if contact and not pushup:
        axis.plot(
            times,
            [float(r["assist_force_z_N"]) for r in trace],
            color="#557bd1",
            label="External support z [N]",
        )
        axis.axhline(float(trace[0]["weight_N"]), color="#6e737b", linestyle="--", label="mg reference")
    elif not pushup and "target_angle_rad" in trace[0]:
        axis.plot(
            times,
            [float(r["target_angle_rad"]) for r in trace],
            color="#d38422",
            linestyle="--",
            label="Engineering target",
        )
    axis.legend(fontsize=6)
    axis.set(xlabel="Physical time [s]", ylabel=label)
    axis.grid(alpha=0.2)
    cursor = axis.axvline(times[0], color="#ed8b23")
    if pushup:
        groups = (("pectoralis_major", "Pectoralis"), ("triceps_brachii", "Triceps"),
                  ("serratus_anterior", "Serratus"), ("rectus_abdominis", "Rectus abd."), ("deltoid", "Deltoid"))
        if "lumbar_muscles_activation" in trace[0]:
            groups = (("pectoralis_major", "Pectoralis"), ("triceps_brachii", "Triceps"),
                      ("hand_tendons", "Forearm/hand"), ("lumbar_muscles", "Lumbar"), ("abdominal_muscles", "Abdomen"))
        for group, label in groups:
            axes[1].plot(times, [float(r[group + "_activation"]) for r in trace], label=label)
        axes[1].set(xlabel="Physical time [s]", ylabel="Mean path activation [0,1]", ylim=(0, 1))
        axes[1].legend(fontsize=6, ncol=2)
        axes[1].grid(alpha=.2)
        muscle_cursor = axes[1].axvline(times[0], color="#ed8b23")
        if hand_view:
            axis.clear()
            axes[1].clear()
            for side, color in (("r", "#006c84"), ("l", "#c56b2b")):
                axis.plot(times, [float(r[f"hand_{side}_force_z_N"]) for r in trace], color=color, label=side.upper() + " hand")
                axes[1].plot(times, [float(r[f"flexion_{side}_rad"]) for r in trace], color=color, label=side.upper() + " flexion")
                axes[1].plot(times, [float(r[f"deviation_{side}_rad"]) for r in trace], color=color, linestyle="--", label=side.upper() + " deviation")
            axis.set(xlabel="Physical time [s]", ylabel="Hand ground force z [N]")
            axes[1].set(xlabel="Physical time [s]", ylabel="Native wrist coordinate [rad]")
            for plot in (axis, axes[1]):
                plot.legend(fontsize=6, ncol=2)
                plot.grid(alpha=.2)
            cursor = axis.axvline(times[0], color="#ed8b23")
            muscle_cursor = axes[1].axvline(times[0], color="#ed8b23")
        if chest_view:
            axis.clear()
            axes[1].clear()
            for side, color in (("r", "#006c84"), ("l", "#c56b2b")):
                axis.plot(times, [float(r[f"pectoralis_{side}_absolute_path_force_N"]) for r in trace], color=color, label=side.upper())
                axes[1].plot(times, [float(r[f"pectoralis_{side}_activation"]) for r in trace], color=color, label=side.upper())
            axis.set(xlabel="Physical time [s]", ylabel="Force [N]")
            axes[1].set(xlabel="Physical time [s]", ylabel="Activation [0,1]", ylim=(0, 1))
            for plot in (axis, axes[1]):
                plot.legend(fontsize=6)
                plot.grid(alpha=.2)
            cursor = axis.axvline(times[0], color="#ed8b23")
            muscle_cursor = axes[1].axvline(times[0], color="#ed8b23")
    figure.savefig(out / "plot.png")
    for frame in expected["frames"]:
        index = frame["frame"]
        raw = work / f"raw_{index:04d}.png"
        with Image.open(raw) as source:
            picture = source.convert("RGB")
            if picture.size != (settings["width"], settings["height"]) or np.asarray(picture).std() < 3:
                raise ValueError("blank or incorrect render frame")
        draw = ImageDraw.Draw(picture)
        draw.rectangle((0, 0, picture.width, 50), fill="#101923")
        kind = (
            "PUSH-UP / " + {
                "muscle": "MUSCLE CONTROL", "external": "EXTERNAL JOINT CONTROL",
                "assisted_muscle": "MUSCLES + EXTERNAL JOINT ASSISTANCE",
            }[expected["model"]["derivation"]["parameters"]["control"]]
            if pushup else
            "EXTERNAL PELVIS SUPPORT"
            if expected["model"].get("derivation", {}).get("controller")
            else "CONTACT TRANSIENT"
            if contact
            else "SOFT PELVIS FIXTURE / EXTERNAL ELBOW SERVO"
            if expected.get("scenario_id") == "elbow_tracking"
            else "SOFT PELVIS FIXTURE / EXTERNAL JOINT LOAD"
        )
        if pushup:
            kind += " / " + expected["model"]["derivation"].get("hand_support", "legacy_point").upper()
            acceptance = expected.get("acceptance", {})
            if acceptance.get("full_pushup") == "FAIL":
                label = ("INCOMPLETE CYCLE" if acceptance.get("full_cycle_kinematics") == "FAIL"
                         else "EXERCISE GATES FAILED")
                kind = label + " / " + kind
            if expected["model"]["derivation"]["parameters"].get("palm_technique") == "chest_level":
                kind += " / CHEST-LEVEL WIDE PALMS"
            if expected["model"]["derivation"]["parameters"].get("palm_technique") == "chest_full":
                kind += " / WRIST RANGE DERIVATION"
            if expected["model"]["derivation"]["parameters"].get("knuckle_technique") == "neutral_tucked":
                kind += " / TUCKED ELBOWS"
        boundary = " | FIXED XY SUPPORTS" if pushup and expected["model"]["derivation"].get("support_boundary") == "fixed_points" else ""
        draw.text((8, 6), "UsefulWrong / MS-Human-700 | " + kind, fill="#e3eaf0")
        draw.text(
            (8, 24),
            f"t={frame['time_s']:.3f} s | Blender Cycles | replay of computed states{boundary} | no clinical/balance validation",
            fill="#edb163",
        )
        cursor.set_xdata([frame["time_s"], frame["time_s"]])
        if pushup:
            muscle_cursor.set_xdata([frame["time_s"], frame["time_s"]])
        figure.canvas.draw()
        graph = Image.fromarray(np.asarray(figure.canvas.buffer_rgba())[:, :, :3].copy())
        if picture.width >= 640 and not regional_view and expected["request"].get("recipe") != "pushup_cinematic":
            graph.thumbnail((picture.width - 16 if pushup else picture.width // 3, picture.height // 3))
            picture.paste(graph, (picture.width - graph.width - 8, picture.height - graph.height - (30 if pushup else 8)))
        region = expected.get("regional_layer") or ("lumbar_muscles" if settings.get("camera_view") == "lumbar" else "abdominal_muscles")
        regional_values = {p["actuator"]: p["activation"] for p in frame["paths"] if region in p.get("regions", [])} if regional_view else {}
        legend = (
            "Z-Anatomy | Bilateral rectus | Illustrative fit | Floor hidden for inspection"
            if "rectus_atlas" in expected["request"]["layers"] else
            "BodyParts3D / DBCLS | Right clavicular pectoralis | Illustrative skinning | No activation mapping"
            if "atlas" in expected else
            "Amber: ground reaction [N] | Joint axes and center of mass"
            if expected["request"].get("recipe") == "pushup_scientific" else
            f"Pectoral paths: R {float(frame['metrics']['pectoralis_r_absolute_path_force_N']):.1f} N, L {float(frame['metrics']['pectoralis_l_absolute_path_force_N']):.1f} N | Activation blue 0 -> red 1"
            if chest_view else
            "Region mean saved activation: " + f"{np.mean(list(regional_values.values())):.3f}"
            + " | Blue 0 -> red 1 | Paths are not muscle volumes"
            if regional_values else
            "Mechanical pads cyan; force amber; ground moment purple | Rigid finger pose; ligaments not modeled"
            if hand_view else
            "GRF amber; external support absent | Path activation: blue 0 -> red 1 | Paths are not muscle volumes"
            if pushup and expected["model"]["derivation"]["parameters"]["control"] == "muscle" else
            "External joint assistance USED | Path activation: blue 0 -> red 1 | Paths are not muscle volumes"
            if pushup else
            "GRF amber / external support blue; scale 0.0006 m/N"
            if contact and "contact_forces" in expected["request"]["layers"]
            else (
                "Path color: saved activation [0,1], blue 0 -> red 1; paths are not muscle volumes"
                if any(f["paths"] for f in expected["frames"])
                and (expected["request"]["profile"] != "cinematic" or pushup)
                else "Native tendon paths; red is explanatory; materials/light are artistic"
                if any(f["paths"] for f in expected["frames"])
                else "Selected native model layers; materials/light are presentation"
            )
        )
        draw.rectangle((0, picture.height - 22, picture.width if pushup else min(picture.width, 660), picture.height), fill="#101923")
        draw.text((8, picture.height - 17), legend, fill="#dce5ed")
        name = f"frame_{index:04d}.png"
        picture.save(work / name)
        frames.append(picture)
    plt.close(figure)
    frames[-1].save(out / "preview.png")
    for phase, source_index in expected.get("phase_source_indices", {}).items():
        frame = next(f for f in expected["frames"] if f["source_index"] == source_index)
        frames[frame["frame"]].save(out / (phase + ".png"))
    palette_samples = Image.new("RGB", (480, 90))
    for column, index in enumerate((0, len(frames) // 2, len(frames) - 1)):
        sample = frames[index].copy()
        sample.thumbnail((160, 90))
        palette_samples.paste(sample, (160 * column, 0))
    palette = palette_samples.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
    gif_boundaries = [round(i * 100 / settings["fps"]) * 10 for i in range(len(frames) + 1)]
    gif_intervals = [b - a for a, b in zip(gif_boundaries, gif_boundaries[1:])]
    indexed[0].save(
        out / "animation.gif",
        save_all=True,
        append_images=indexed[1:],
        duration=gif_intervals,
        loop=0,
        optimize=False,
    )
    expected["timing"].update(
        gif_frame_interval_ms=gif_intervals[0] if len(set(gif_intervals)) == 1 else None,
        gif_frame_intervals_ms=gif_intervals,
        gif_duration_s=gif_boundaries[-1] / 1000,
        gif_clock="GIF centisecond-quantized presentation; physical times are in each frame",
    )
    write_json(work / "expected.json", expected)
    with managed_process(
        [
            os.environ.get("HMM_FFMPEG", "ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-framerate",
            str(settings["fps"]),
            "-i",
            str(work / "frame_%04d.png"),
            "-frames:v",
            str(len(frames)),
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(out / "animation.mp4"),
        ],
        memory=2 * 1024**3, linux_group=True, stdin=subprocess.DEVNULL,
    ) as encoder:
        if encoder.wait(timeout=90):
            raise RuntimeError(f"FFmpeg exited {encoder.returncode}")
    with zipfile.ZipFile(out / "frames.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for frame in expected["frames"]:
            name = f"frame_{frame['frame']:04d}.png"
            archive.write(work / name, name)
    with zipfile.ZipFile(out / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (folder / "input").iterdir():
            if path.name not in expected.get("atlas", {}).get("source", {}).get("files", {}):
                archive.write(path, path.name)
    with zipfile.ZipFile(out / "scene.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (work / "usd").rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(work).as_posix())
        archive.write(work / "expected.json", "expected.json")
        if (work / "atlas_surfaces.npz").is_file():
            archive.write(work / "atlas_surfaces.npz", "atlas_surfaces.npz")
    write_json(
        out / "frames.json",
        {
            "source_run_id": expected["run_id"],
            "source_files": expected["source_files"],
            "units": expected["units"],
            "coordinates": expected["coordinates"],
            "timing": expected["timing"],
            "phase_source_indices": expected.get("phase_source_indices", {}),
            "frames": [
                {
                    "frame": f["frame"],
                    "source_index": f["source_index"],
                    "time_s": f["time_s"],
                    "state_sha256": f["state_sha256"],
                    "png_sha256": digest(work / f"frame_{f['frame']:04d}.png"),
                }
                for f in expected["frames"]
            ],
        },
    )


def process_job(job_id):
    folder = job_dir(job_id)
    record = read_job(job_id)
    started = time.monotonic()
    record.update(status="running", started_at=now(), progress={"phase": "exporting"})
    write_json(folder / "job.json", record)
    try:
        request = record["request"]
        if "render_lock_sha256" in request and (
            request["render_lock_sha256"] != render_lock_digests() or request["render_code_sha256"] != code_sha256()
        ):
            raise ValueError("render worker source or dependency lock hash differs from the submission")
        options = RenderOptions.model_validate(request["options"]).model_dump()
        source_integrity(folder, record)
        from .scene_export import export_scene

        expected = export_scene({"path": folder, "record": record})
        record["progress"] = {"phase": "cycles"}
        write_json(folder / "job.json", record)
        fallback = None
        try:
            performance = blender(
                folder, {**options, "timeout_s": max(1, options["timeout_s"] - (time.monotonic() - started))}
            )
        except RuntimeError as exc:
            if options["device"] == "cpu" or not any(
                s in str(exc).lower() for s in ("out of memory", "memoryerror", "cuda", "optix")
            ):
                raise
            fallback = {"reason": str(exc)[-1200:], "action": "retry actual rendering on CPU"}
            performance = blender(
                folder,
                {**options, "timeout_s": max(1, options["timeout_s"] - (time.monotonic() - started))},
                "cpu",
            )
        package_media(folder, expected)
        source_integrity(folder, record)
        if time.monotonic() - started > options["timeout_s"]:
            raise TimeoutError("Render job wall-time budget exceeded")
        out = folder / "artifacts"
        source_run = json.loads((folder / "input/manifest.json").read_text(encoding="utf-8"))
        info = json.loads((out / "blender_render.json").read_text(encoding="utf-8"))
        environment = Path(os.environ.get("HMM_RENDER_ENVIRONMENT", home() / "runtime-environment.json"))
        renderer_environment = (json.loads(environment.read_text(encoding="utf-8")) if environment.is_file() else {
            "source_sha256": code_sha256(), "python": platform.python_version(),
            "platform": platform.platform(), "lock_sha256": render_lock_digests(),
            "packages": {name: importlib.metadata.version(name) for name in ("mujoco", "usd-core")},
        })
        passport = {
            "schema_version": "1.0",
            "job_id": job_id,
            "source_run_id": expected["run_id"],
            "model": expected["model"],
            "engine": expected["engine"],
            "source_files": record["source_files"],
            **({"atlas_source_files": record["atlas_source_files"]} if "atlas_source_files" in record else {}),
            "simulation": source_run["execution"],
            "source_scientific": source_run["scientific"],
            "method": "saved-state kinematics/geometry replay through official USDExporter, Blender USD import and checked transform baking; no physics integration",
            "renderer": info,
            "performance": performance,
            "fallback": fallback,
            "request": record["request"],
            "timing": expected["timing"],
            "coordinates": expected["coordinates"],
            "units": expected["units"],
            "geometry_validation": json.loads((out / "geometry_validation.json").read_text(encoding="utf-8")),
            "mesh_normalization": expected["mesh_normalization"],
            "layers": {n: LAYERS[n] for n in record["request"]["layers"]},
            "anatomy": {
                "source": "Pinned native MS-Human-700 meshes; external anatomical assets not integrated",
                "license": expected["model"]["license"],
                "mapping": "Native compiled geom/body frames and mesh vertex landmarks; no fitted atlas or inferred tissue deformation",
                "external_registration": "registration_unverified",
                "path_inventory": expected.get("path_inventory"),
                "hands": expected["model"].get("derivation", {}).get("hands"),
            },
            "scientific": {
                "validation_level": "numerical_sanity",
                "scope": "named geometric/time equality checks only",
                "limitations": record["scientific"]["limitations"]
                + [
                    "Materials, studio light and camera are presentation parameters, not tissue physical properties.",
                    "Muscle paths are lines, not anatomical muscle volumes.",
                    "Native soft knee couplings can drift during the original dynamics; replay does not correct them.",
                ],
            },
            "software_licenses": json.loads((home() / "renderer.lock.json").read_text(encoding="utf-8")),
            "renderer_environment": renderer_environment,
            "total_seconds": time.monotonic() - started,
            "test_failure_injection": os.environ.get("HMM_TEST_RENDER_FAILURE"),
        }
        if "atlas" in expected:
            atlas = {k: v for k, v in expected["atlas"].items() if k != "faces"}
            atlas["frames"] = [dict(f["atlas_checks"], source_index=f["source_index"], time_s=f["time_s"],
                                    state_sha256=f["state_sha256"]) for f in expected["frames"]]
            atlas["blender"] = passport["geometry_validation"]["atlas_surface"]
            passport["anatomy"].update(
                source="Pinned native MS-Human-700 and " + atlas["anatomical_id"],
                mapping=atlas["method"],
                external_registration=atlas["status"],
                atlas_license=atlas["source"]["license"],
                atlas_report="anatomy_registration.json",
            )
            write_json(out / "anatomy_registration.json", atlas)
        write_json(out / "passport.json", passport)
        def source_json(name):
            path = folder / "input" / name
            return json.loads(path.read_text(encoding="utf-8")) if name in record["source_files"] else None

        contract = evidence_context(source_run, source_json("summary.json"), source_json("validation.json"))
        contract["render_job_id"] = job_id
        contract["renderer"] = info
        contract["render_code_sha256"] = passport["renderer_environment"]["source_sha256"]
        contract["numeric_checks"] += [
            {"name": name, "status": "PASS", "threshold": expected["geometry_validation"].get(tolerance)}
            for name, tolerance in (("blender_translation", "translation_tolerance_m"),
                                    ("blender_rotation", "rotation_matrix_tolerance"),
                                    ("blender_landmarks", "landmark_tolerance_m"))
        ]
        mapping = expected.get("atlas", {}).get("status", "native")
        if "atlas" in expected:
            contract["sources"] = [*contract["sources"], atlas["source"]]
            contract["scope_limitations"] = [*contract["scope_limitations"], *atlas["limitations"]]
            contract["numeric_checks"].append({
                "name": "blender_atlas_surface_transfer", "status": "PASS", "unit": "m",
                "threshold": atlas["blender"]["vertex_tolerance_m"],
                "value": max(f["max_vertex_error_m"] for f in atlas["blender"]["frames"]),
            })
        files = {
            p.name: artifact_metadata(p)
            for p in sorted(out.iterdir())
            if p.is_file() and p.suffix != ".blend1" and p.name != "evidence.json"
        }
        claims = []
        for name, metadata in files.items():
            scope = ("unavailable" if name in {"source.zip", "blender_render.json", "frames.json"} else
                     "native" if name == "plot.png" else mapping)
            claims.append({
                "claim_id": "artifact:" + name, "quantity": "render_artifact",
                "value": metadata, "unit": None,
                "time_window_s": [expected["frames"][0]["time_s"], expected["frames"][-1]["time_s"]],
                "side": ("bilateral" if "structures" in atlas else "right") if scope == "illustrative" else None,
                "structure": expected.get("atlas", {}).get("anatomical_id") if scope == "illustrative" else None,
                "anatomical_mapping_status": scope, "reference_comparison": {"status": "NOT_AVAILABLE"},
                "evidence_class": "internally_checked" if name != "source.zip" else "computed_only",
                "validation_status": "unvalidated",
                "confidence_explanation": "Blender transfer checks compare to the saved model and optional skinning rig only.",
            })
        write_json(out / "evidence.json", dict(contract, claims=claims))
        files["evidence.json"] = artifact_metadata(out / "evidence.json")
        if (
            not {
                "preview.png",
                "animation.mp4",
                "animation.gif",
                "scene.blend",
                "scene.zip",
                "source.zip",
                "frames.zip",
                "passport.json",
            }
            <= files.keys()
        ):
            raise ValueError("required render output missing")
        if sum(v["bytes"] for v in files.values()) > 512 * 1024 * 1024 or any(
            v["bytes"] > MAX_FILE for v in files.values()
        ):
            raise ValueError("render artifact budget exceeded")
        record.update(
            status="completed",
            completed_at=now(),
            artifacts=files,
            progress={"phase": "completed", "completed_frames": len(expected["frames"])},
            scientific={
                "validation_level": "numerical_sanity",
                "geometry_status": "validated_for_named_checks",
                "anatomical_registration": (atlas["status"] if "atlas" in expected else
                                            "native_model_only; external registration_unverified"),
                "acceptance": contract["acceptance"],
                "human_validation_status": contract["human_validation_status"],
                "human_safety_status": contract["human_safety_status"],
            },
            render_backend=info["device"],
            seconds=time.monotonic() - started,
        )
    except Exception as exc:
        code = (
            "timeout"
            if isinstance(exc, TimeoutError)
            else "integrity_error"
            if isinstance(exc, ValueError) and ("hash" in str(exc) or "trajectory" in str(exc))
            else "render_failed"
        )
        record.update(
            status="failed",
            completed_at=now(),
            error={"code": code, "message": str(exc)[-3000:]},
            progress={"phase": "failed"},
        )
    write_json(folder / "job.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    root = queue_root()

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    with file_lock(root / ".worker.lock", blocking=False) as acquired:
        if not acquired:
            raise RuntimeError("one render worker already owns this queue")
        for path in sorted(root.glob("*/job.json")):
            record = read_job(path.parent.name)
            if record["status"] == "running":
                record.update(
                    status="failed",
                    completed_at=now(),
                    error={
                        "code": "interrupted",
                        "message": "Worker restarted during rendering; partial files retained.",
                    },
                )
                write_json(path, record)
        try:
            while True:
                jobs = [read_job(p.parent.name) for p in sorted(root.glob("*/job.json"))]
                queued = sorted((j for j in jobs if j["status"] == "queued"), key=lambda j: j["created_at"])
                if queued:
                    print(
                        json.dumps(
                            {
                                "job_id": queued[0]["job_id"],
                                "status": process_job(queued[0]["job_id"])["status"],
                            }
                        ),
                        flush=True,
                    )
                elif args.once:
                    break
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
