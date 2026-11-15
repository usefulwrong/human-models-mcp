"""Native model frames plus measured COM, contact points and declared wrench overlays."""

import csv
import hashlib
import json
import os
from pathlib import Path


def render_contact(mj, model, output: Path, recipe: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from OpenGL import GL
    from PIL import Image, ImageDraw

    saved = np.load(output / "trajectory.npz", allow_pickle=False)
    states, times, specification = saved["states"], saved["time_s"], int(saved["state_spec"])
    support = json.loads((output / "support.json").read_text())["samples"]
    with (output / "series.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    data = mj.MjData(model)
    camera = mj.MjvCamera()
    camera.lookat[:] = [0, 0, .85]
    camera.distance, camera.azimuth, camera.elevation = 2.8, 130, -12
    option = mj.MjvOption()
    option.flags[mj.mjtVisFlag.mjVIS_JOINT] = True
    model.vis.global_.offwidth, model.vis.global_.offheight = 640, 640
    model.vis.quality.shadowsize, model.vis.quality.offsamples = 512, 0
    palette = {"figure.facecolor": "#101923", "axes.facecolor": "#101923", "text.color": "#dfe7ef",
               "axes.labelcolor": "#dfe7ef", "xtick.color": "#dfe7ef", "ytick.color": "#dfe7ef",
               "axes.edgecolor": "#708090", "font.size": 9}
    frames, dashboards = [], []
    with plt.rc_context(palette):
        fig, axes = plt.subplots(3, 1, figsize=(6.4, 6.4), dpi=100, layout="constrained")
        axes[0].plot(times, [float(r["grf_z_N"]) for r in rows], color="#ffbd69", label="Ground reaction z")
        axes[0].plot(times, [float(r["assist_force_z_N"])-float(recipe.get("downward_load_N", 0)) for r in rows], color="#8bafff", label="External pelvis force z")
        axes[0].axhline(float(rows[0]["weight_N"]), color="#dfe7ef", linestyle="--", label="mg (reference)", alpha=.65)
        axes[0].set_ylabel("World vertical force [N]")
        axes[0].legend(fontsize=7, ncol=2)
        axes[0].set_xlabel("Simulation time [s]")
        axes[1].plot(times, [float(r["com_z_m"]) for r in rows], color="#56c9d8", label="Whole-model COM")
        axes[1].plot(times, [float(r["root_z_m"]) for r in rows], color="#8bafff", label="Pelvis origin")
        axes[1].set_ylabel("Height [m]")
        axes[1].set_xlabel("Simulation time [s]")
        axes[1].legend(fontsize=7)
        for axis in axes[:2]:
            axis.grid(alpha=.15)
            axis.ticklabel_format(axis="y", useOffset=False)
        cursors = [axis.axvline(0, color="#ffbd69", linewidth=1) for axis in axes[:2]]
        axes[2].set_xlim(-.18, .22)
        axes[2].set_ylim(-.18, .18)
        axes[2].set_aspect("equal", adjustable="box")
        axes[2].set_xlabel("World x [m]")
        axes[2].set_ylabel("World y [m]")
        axes[2].set_title("Force-bearing contact hull; inclusion is not balance validation", fontsize=8)
        polygon, = axes[2].plot([], [], color="#ffbd69", linewidth=1.5, label="Point-contact hull")
        com_dot, = axes[2].plot([], [], "o", color="#56c9d8", label="COM projection")
        cop_dot, = axes[2].plot([], [], "x", color="#df94ff", label="Ground-wrench CoP")
        axes[2].legend(fontsize=7, loc="upper right")
        indices = np.unique(np.linspace(0, len(states)-1, 21, dtype=int))
        with mj.Renderer(model, height=640, width=640) as renderer:
            for index in indices:
                mj.mj_setState(model, data, states[index], specification)
                mj.mj_forward(model, data)
                if not np.array_equal(data.qpos, saved["qpos"][index]) or abs(data.time-times[index]) > 1e-12:
                    raise ValueError("render state/time differs from numerical archive")
                geometry, row = support[index], rows[index]
                center = np.array(geometry["com_world_m"])
                if np.linalg.norm(data.subtree_com[model.body("pelvis").id]-center) > 1e-12:
                    raise ValueError("render COM differs from numerical sample")
                renderer.update_scene(data, camera=camera, scene_option=option)
                scene = renderer.scene

                def marker(position, color, radius=.015):
                    if scene.ngeom >= scene.maxgeom:
                        raise ValueError("contact overlay scene capacity exceeded")
                    geom = scene.geoms[scene.ngeom]
                    mj.mjv_initGeom(geom, mj.mjtGeom.mjGEOM_SPHERE, np.array([radius, 0, 0]), position, np.eye(3).reshape(-1), np.array(color, dtype=np.float32))
                    scene.ngeom += 1

                def line(start, end, color, arrow=False):
                    if scene.ngeom >= scene.maxgeom:
                        raise ValueError("contact overlay scene capacity exceeded")
                    geom = scene.geoms[scene.ngeom]
                    mj.mjv_initGeom(geom, mj.mjtGeom.mjGEOM_ARROW if arrow else mj.mjtGeom.mjGEOM_LINE, np.zeros(3), np.zeros(3), np.eye(3).reshape(-1), np.array(color, dtype=np.float32))
                    mj.mjv_connector(geom, mj.mjtGeom.mjGEOM_ARROW if arrow else mj.mjtGeom.mjGEOM_LINE, .008 if arrow else 2, start, end)
                    scene.ngeom += 1

                marker(center, [.34, .79, .85, 1], .025)
                line(center, np.array([center[0], center[1], .003]), [.34, .79, .85, .7])
                hull = geometry["polygon_xy_m"]
                for point in hull:
                    marker(np.array([point[0], point[1], .004]), [1, .74, .41, 1], .009)
                if len(hull) > 1:
                    for a, b in zip(hull, hull[1:]+hull[:1]):
                        line(np.array([*a, .004]), np.array([*b, .004]), [1, .74, .41, 1])
                cop = geometry["cop_xy_m"]
                if cop:
                    start = np.array([*cop, .004])
                    ground = np.array([float(row[f"grf_{axis}_N"]) for axis in "xyz"])
                    line(start, start+.0008*ground, [1, .74, .41, 1], True)
                if recipe["controller"]:
                    position = data.xipos[model.body("pelvis").id]
                    force = np.array([float(row[f"assist_force_{axis}_N"]) for axis in "xyz"])
                    line(position, position+.0008*force, [.55, .69, 1, 1], True)
                pixels = renderer.render()
                if pixels.std() < 1:
                    raise ValueError("blank contact render")
                name = f"frame_{index:04d}.png"
                picture = Image.fromarray(pixels)
                picture.save(output / name)
                frames.append({"artifact_id": name, "state_index": int(index), "time_s": float(data.time),
                               "state_sha256": hashlib.sha256(states[index].tobytes()).hexdigest(),
                               "sha256": hashlib.sha256((output/name).read_bytes()).hexdigest()})
                for cursor in cursors:
                    cursor.set_xdata([data.time, data.time])
                closed = hull+hull[:1] if len(hull) > 1 else hull
                polygon.set_data([p[0] for p in closed], [p[1] for p in closed])
                com_dot.set_data([center[0]], [center[1]])
                cop_dot.set_data([cop[0]] if cop else [], [cop[1]] if cop else [])
                fig.canvas.draw()
                plot = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
                board = Image.new("RGB", (1280, 720), "#101923")
                board.paste(picture, (0, 76))
                board.paste(plot, (640, 76))
                draw = ImageDraw.Draw(board)
                kind = "EXTERNAL PELVIS PD SUPPORT" if recipe["controller"] else "PASSIVE CONTACT PROBE"
                draw.text((15, 8), "UsefulWrong | MS-Human-700 Locomotion / MuJoCo 3.17.0 | "+kind, fill="#dfe7ef")
                draw.text((15, 28), f"t={data.time:.3f} s | CPU physics | capsule contacts | COM cyan; GRF amber; external support blue", fill="#ffbd69")
                draw.text((15, 48), f"Named numerical checks only | force residual {float(row['force_residual_N']):.2g} N; moment residual {float(row['moment_residual_Nm']):.2g} N m | no balance/safety certification", fill="#dfe7ef")
                dashboards.append(board)
            vendor, device = GL.glGetString(GL.GL_VENDOR).decode(), GL.glGetString(GL.GL_RENDERER).decode()
        fig.savefig(output / "plots.png")
        plt.close(fig)
    dashboards[-1].save(output / "overview.png")
    durations = [max(20, round(10000*(times[b]-times[a]))) for a, b in zip(indices, indices[1:])]
    durations.append(durations[-1])
    palette_image = dashboards[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    indexed = [board.quantize(palette=palette_image, dither=Image.Dither.NONE) for board in dashboards]
    indexed[0].save(output / "animation.gif", save_all=True, append_images=indexed[1:], duration=durations, loop=0, optimize=False)
    (output / "pose.png").write_bytes((output / frames[-1]["artifact_id"]).read_bytes())
    def digest(name):
        return hashlib.sha256((output/name).read_bytes()).hexdigest()
    info = {"status": "rendered", "model_id": "ms_human_700_locomotion", "method": "dynamic_forward", "render_backend": "nvidia_egl" if os.environ.get("MUJOCO_GL") == "egl" and "NVIDIA" in vendor else os.environ.get("MUJOCO_GL", "osmesa"),
            "gl_vendor": vendor, "gl_renderer": device, "sample": len(states)-1, "simulation_time_s": float(times[-1]),
            "timestep_s": model.opt.timestep, "integration_steps": len(states)-1, "width": 640, "height": 640,
            "camera": {"lookat": camera.lookat.tolist(), "distance": camera.distance, "azimuth": camera.azimuth, "elevation": camera.elevation},
            "qpos": saved["qpos"][-1].tolist(), "state_archive_sha256": digest("trajectory.npz"), "series_sha256": digest("series.csv"),
            "support_sha256": digest("support.json"), "contact_metadata_sha256": digest("contacts.json"), "frames": frames,
            "qpos_hash_encoding": "UTF-8 json.dumps(qpos) with Python default separators", "state_hash_encoding": {"numpy_dtype": states.dtype.str, "order": "C", "operation": "states[index].tobytes()"},
            "animation_artifact": "animation.gif", "playback": "10 times slower plus one frame interval at end", "joint_axes": True,
            "animation_encoding": {"global_palette_colors": 128, "dither": "none", "dashboard_pixels": [1280, 720], "raw_pngs": "native full resolution retained"},
            "overlays": {"force_arrow_scale_m_per_N": .0008, "ground_marker_z_m": .004, "COM": "mass-weighted model COM", "support": "saved force-bearing contact hull", "arrows": "saved world ground reaction and optional explicit external support"},
            "note": "Native geometry restored from actual integration state. Auxiliary markers do not add collision geometry. Point-contact hull and CoP inclusion do not establish balance or medical safety."}
    info["qpos_sha256"] = hashlib.sha256(json.dumps(info["qpos"]).encode()).hexdigest()
    for name in ("frames.json", "frame.json"):
        (output/name).write_text(json.dumps(info, indent=2))
    return info
