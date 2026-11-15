"""Headless frames and plots reconstructed from the saved integration states."""

import csv
import hashlib
import json
import os
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_motion(mj, model, output: Path, joint: int, derivation: dict) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from OpenGL import GL
    from PIL import Image, ImageDraw

    saved = np.load(output / "trajectory.npz", allow_pickle=False)
    states, times = saved["states"], saved["time_s"]
    spec = int(saved["state_spec"])
    with (output / "series.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    data = mj.MjData(model)
    mj.mj_setState(model, data, states[0], spec)
    mj.mj_forward(model, data)
    camera = mj.MjvCamera()
    camera.lookat[:] = data.xanchor[joint]
    camera.distance, camera.azimuth, camera.elevation = 1.75, -90, -10
    option = mj.MjvOption()
    option.flags[mj.mjtVisFlag.mjVIS_JOINT] = True
    model.vis.global_.offwidth, model.vis.global_.offheight = 640, 480
    model.vis.quality.shadowsize, model.vis.quality.offsamples = 512, 0
    palette = {"figure.facecolor": "#101923", "axes.facecolor": "#101923", "text.color": "#dfe7ef",
               "axes.labelcolor": "#dfe7ef", "xtick.color": "#dfe7ef", "ytick.color": "#dfe7ef",
               "axes.edgecolor": "#708090", "font.size": 9}
    with plt.rc_context(palette):
        fig, axes = plt.subplots(3, 1, figsize=(4.8, 4.8), dpi=100, sharex=True, layout="constrained")
        for axis, key, label in zip(axes, ("angle_rad", "actuator_force_N", "applied_torque_Nm"),
                                    ("Elbow angle [rad]", "BIClong_r force [N]", "Applied torque [N m]"), strict=True):
            axis.plot(times, [float(row[key]) for row in rows], color="#56c9d8", linewidth=1.8)
            axis.set_ylabel(label)
            axis.grid(alpha=.16)
            axis.ticklabel_format(axis="y", useOffset=False)
        if "target_angle_rad" in rows[0]:
            axes[0].plot(times, [float(row["target_angle_rad"]) for row in rows], "--", color="#ffbd69", label="Engineering reference")
            axes[0].legend(fontsize=7)
        axes[-1].set_xlabel("Simulation time [s]")
        fig.savefig(output / "plots.png")
        cursors = [axis.axvline(0, color="#ffbd69", linewidth=1) for axis in axes]
        indices = np.unique(np.linspace(0, len(states) - 1, 21, dtype=int))
        frames, dashboards = [], []
        with mj.Renderer(model, height=480, width=640) as renderer:
            for index in indices:
                mj.mj_setState(model, data, states[index], spec)
                mj.mj_forward(model, data)
                if not np.array_equal(data.qpos, saved["qpos"][index]) or abs(data.time - times[index]) > 1e-12:
                    raise ValueError("saved-state reconstruction changed qpos/time")
                renderer.update_scene(data, camera=camera, scene_option=option)
                pixels = renderer.render()
                if pixels.std() < 1:
                    raise ValueError("blank motion frame")
                name = f"frame_{index:04d}.png"
                picture = Image.fromarray(pixels)
                picture.save(output / name)
                frames.append({"artifact_id": name, "state_index": int(index), "time_s": float(data.time),
                               "sha256": digest(output / name),
                               "state_sha256": hashlib.sha256(states[index].tobytes()).hexdigest()})
                for cursor in cursors:
                    cursor.set_xdata([data.time, data.time])
                fig.canvas.draw()
                plot = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
                dashboard = Image.new("RGB", (1120, 548), "#101923")
                dashboard.paste(picture, (0, 60))
                dashboard.paste(plot, (640, 60))
                draw = ImageDraw.Draw(dashboard)
                mode = "PD servo / synthetic reference" if "target_angle_rad" in rows[0] else "prescribed elbow torque"
                draw.text((16, 10), "UsefulWrong | MS-Human-700 / MuJoCo 3.17.0 | pelvis fixture + " + mode, fill="#dfe7ef")
                draw.text((16, 30), f"t = {data.time:.3f} s | model geometry + joint axes | CPU physics | numerical sanity only", fill="#ffbd69")
                dashboards.append(dashboard)
            vendor = GL.glGetString(GL.GL_VENDOR).decode()
            device = GL.glGetString(GL.GL_RENDERER).decode()
        plt.close(fig)
    dashboards[-1].save(output / "overview.png")
    durations = [max(20, round(10000 * (times[b] - times[a]))) for a, b in zip(indices, indices[1:])]
    durations.append(durations[-1])
    dashboards[0].save(output / "animation.gif", save_all=True, append_images=dashboards[1:],
                       duration=durations, loop=0, optimize=True)
    (output / "pose.png").write_bytes((output / frames[-1]["artifact_id"]).read_bytes())
    backend = "nvidia_egl" if os.environ.get("MUJOCO_GL") == "egl" and "NVIDIA" in vendor else os.environ.get("MUJOCO_GL", "osmesa")
    camera_info = {"lookat": camera.lookat.tolist(), "distance": camera.distance,
                   "azimuth": camera.azimuth, "elevation": camera.elevation}
    info = {"status": "rendered", "render_backend": backend, "gl_vendor": vendor, "gl_renderer": device,
            "model_id": "ms_human_700", "method": "dynamic_forward", "sample": len(states) - 1,
            "simulation_time_s": float(times[-1]), "integration_steps": len(states) - 1,
            "timestep_s": model.opt.timestep, "qpos": saved["qpos"][-1].tolist(),
            "width": 640, "height": 480, "camera": camera_info,
            "derived_mjcf_sha256": derivation["derived_mjcf_sha256"],
            "state_archive_sha256": digest(output / "trajectory.npz"), "series_sha256": digest(output / "series.csv"),
            "joint_axes": True, "frames": frames, "animation_artifact": "animation.gif",
            "playback": "10 times slower than simulation, plus one frame interval at the end",
            "note": "Saved integration states restored with mj_setState + mj_forward, no integration during rendering. Source muscle paths and skeletal geometry; not tissue volumes or collision certification."}
    info["qpos_sha256"] = hashlib.sha256(json.dumps(info["qpos"]).encode()).hexdigest()
    info["qpos_hash_encoding"] = "UTF-8 json.dumps(qpos) with Python default separators"
    info["state_hash_encoding"] = {"numpy_dtype": saved["states"].dtype.str, "order": "C", "operation": "states[index].tobytes()"}
    for name in ("frame.json", "frames.json"):
        (output / name).write_text(json.dumps(info, indent=2))
    return info
