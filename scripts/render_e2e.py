"""Host orchestration of real SDK/Blender rendering tests; containers never start Docker."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from package_release import image_matches_source, read_image_environment

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("HMM_RENDER_IMAGE", "human-models-mcp-night-renderer:local")


def command(args, env=None, **kwargs):
    subprocess.run(args, cwd=ROOT, env=env, check=True, **kwargs)


def audit_media(folder):
    sandbox = [
        "docker",
        "run",
        "--rm",
        "--name",
        "human-models-mcp-night-visual-audit-" + str(uuid4()),
        "--network",
        "none",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--pids-limit",
        "128",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:size=512m,mode=1777",
        "-v",
        str(folder) + ":/app/check",
    ]
    command([*sandbox, "--entrypoint", "python", IMAGE, "scripts/verify_visual_native.py", "/app/check"])
    command(
        [
            *sandbox,
            "--entrypoint",
            "/opt/blender/blender",
            IMAGE,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            "/app/scripts/verify_visual_blend.py",
            "--",
            "/app/check",
        ]
    )
    info = subprocess.check_output(
        [
            *sandbox,
            "--entrypoint",
            "ffprobe",
            IMAGE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_frames,duration",
            "-of",
            "json",
            "/app/check/animation.mp4",
        ],
        text=True,
    )
    meta = json.loads(info)["streams"][0]
    job = json.loads((folder / "client.json").read_text())["job"]
    options = job["request"]["options"]
    assert (
        int(meta["nb_frames"]) == options["frames"]
        and int(meta["width"]) == options["width"]
        and int(meta["height"]) == options["height"]
    )
    assert abs(float(meta["duration"]) - options["frames"] / options["fps"]) < 0.01
    command(
        [
            *sandbox,
            "--entrypoint",
            "ffmpeg",
            IMAGE,
            "-v",
            "error",
            "-nostdin",
            "-i",
            "/app/check/animation.mp4",
            "-f",
            "null",
            "-",
        ]
    )
    (folder / "independent-media.json").write_text(
        json.dumps({"status": "pass", "ffprobe": meta, "full_video_decode": "pass"}, indent=2) + "\n"
    )
    return {
        "native": json.loads((folder / "independent-native.json").read_text()),
        "blend": json.loads((folder / "independent-blend.json").read_text()),
        "media": meta,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    if not image_matches_source(read_image_environment(IMAGE)):
        raise RuntimeError("Renderer image differs from current source/locks; run make render-build")
    tag = str(uuid4())
    store = ROOT / "reports/e2e-client-runs" / ("v06-science-" + tag)
    store.mkdir(parents=True)
    output = ROOT / "reports/e2e-client-runs" / ("v06-render-" + tag)
    output.mkdir()
    env = {**os.environ, "HMM_RESULTS_DIR": str(store)}
    compose = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if args.gpu:
        compose += ["-f", str(ROOT / "compose.render-gpu.yaml")]
    compose += ["-p", "human-models-mcp-night"]
    command([*compose, "up", "-d", "--no-deps", "renderer"], env=env)
    python = os.environ.get("HMM_CLIENT_PYTHON", str(ROOT / ".client-venv/bin/python"))
    evidence = {}
    cases = [("elbow_tracking", "scientific" if args.gpu else "preview", "gpu" if args.gpu else "cpu")]
    if args.gpu:
        cases += [("elbow_tracking", "cinematic", "gpu"), ("assisted_stance", "scientific", "gpu")]
    else:
        cases += [("assisted_stance", "preview", "gpu")]
    shared_run = None
    camera = None
    for scenario, profile, device in cases:
        folder = output / (scenario + "-" + profile)
        full = args.gpu
        cmd = [
            python,
            str(ROOT / "examples/mcp-client/render_client.py"),
            "--scenario",
            scenario,
            "--profile",
            profile,
            "--device",
            device,
            "--frames",
            "51" if full else "5",
            "--fps",
            "15" if full else "6",
            "--width",
            "960" if full else "480",
            "--height",
            "540" if full else "270",
            "--samples",
            "24" if profile == "cinematic" else "16" if full else "2",
            "--output",
            str(folder),
        ]
        if scenario == "elbow_tracking" and shared_run:
            cmd += ["--run-id", shared_run]
        command(cmd, env=env, timeout=1200)
        data = json.loads((folder / "client.json").read_text())
        passport = json.loads((folder / "passport.json").read_text())
        validation = audit_media(folder)
        actual = passport["renderer"]["device"]["backend"]
        if args.gpu:
            assert actual in ("cuda", "optix"), passport["renderer"]["device"]
        elif device == "gpu":
            assert actual == "cpu_fallback"
        else:
            assert actual == "cpu"
        if scenario == "elbow_tracking":
            shared_run = data["run"]["run_id"]
            if camera:
                assert passport["renderer"]["camera"] == camera
            camera = passport["renderer"]["camera"]
        evidence[scenario + "-" + profile] = {
            "job_id": data["job"]["job_id"],
            "run_id": data["run"]["run_id"],
            "source_hash": data["run"]["artifacts"]["trajectory.npz"]["sha256"],
            "backend": passport["renderer"]["device"],
            "performance": passport["performance"],
            "total_seconds": passport["total_seconds"],
            "output": str(folder.relative_to(ROOT)),
            "independent_checks": validation,
            "artifact_bytes": {k: v["bytes"] for k, v in data["job"]["artifacts"].items()},
        }
    if not args.gpu:
        folder = output / "http-contact"
        container_output = "/app/" + str(folder.relative_to(ROOT))
        command(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "compose.yaml"),
                "-p",
                "human-models-mcp-night",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "python",
                "runtime",
                "examples/mcp-client/render_client.py",
                "--transport",
                "http",
                "--scenario",
                "standing_contact_probe",
                "--frames",
                "5",
                "--width",
                "480",
                "--height",
                "270",
                "--samples",
                "2",
                "--output",
                container_output,
            ],
            env=env,
            timeout=1200,
        )
        data = json.loads((folder / "client.json").read_text())
        validation = audit_media(folder)
        evidence["http-contact"] = {
            "job_id": data["job"]["job_id"],
            "run_id": data["run"]["run_id"],
            "output": str(folder.relative_to(ROOT)),
            "independent_checks": validation,
            "transport": "loopback HTTP in isolated network-none container",
        }
    if not args.gpu:
        folder = output / "elbow-overlays-only"
        command(
            [
                python,
                str(ROOT / "examples/mcp-client/render_client.py"),
                "--run-id",
                shared_run,
                "--scenario",
                "elbow_tracking",
                "--layers",
                "muscle_paths",
                "joint_axes",
                "--frames",
                "3",
                "--width",
                "480",
                "--height",
                "270",
                "--samples",
                "2",
                "--output",
                str(folder),
            ],
            env=env,
            timeout=600,
        )
        data = json.loads((folder / "client.json").read_text())
        evidence["elbow-overlays-only"] = {
            "job_id": data["job"]["job_id"],
            "run_id": shared_run,
            "output": str(folder.relative_to(ROOT)),
            "independent_checks": audit_media(folder),
            "check": "native base meshes hidden; source geometry still numerically checked; only requested overlays rendered",
        }
        folder = output / "loaded_elbow-preview"
        command(
            [
                python,
                str(ROOT / "examples/mcp-client/render_client.py"),
                "--scenario",
                "loaded_elbow",
                "--frames",
                "3",
                "--width",
                "480",
                "--height",
                "270",
                "--samples",
                "2",
                "--output",
                str(folder),
            ],
            env=env,
            timeout=600,
        )
        data = json.loads((folder / "client.json").read_text())
        evidence["loaded_elbow-preview"] = {
            "job_id": data["job"]["job_id"],
            "run_id": data["run"]["run_id"],
            "output": str(folder.relative_to(ROOT)),
            "independent_checks": audit_media(folder),
            "check": "nonzero source muscle activation and path colors; loaded dynamics saved-state transfer",
        }
    else:
        assert (
            max(v for case in evidence.values() for v in case["artifact_bytes"].values()) > 2 * 1024 * 1024
        ), "large-file chunk test needs actual >2 MiB media/scene"
    result = {
        "status": "pass",
        "mode": "gpu" if args.gpu else "cpu",
        "source_store": str(store.relative_to(ROOT)),
        "network": "none for both runtimes",
        "cases": evidence,
    }
    if args.gpu:
        cpu = json.loads((ROOT / "reports/V06_RENDER_CPU.json").read_text())
        pairs = [
            ("elbow_tracking-preview", "elbow_tracking-scientific"),
            ("assisted_stance-preview", "assisted_stance-scientific"),
        ]
        for cpu_name, gpu_name in pairs:
            assert cpu["cases"][cpu_name]["source_hash"] == evidence[gpu_name]["source_hash"], (
                "CPU/GPU rendering changed source integration states"
            )
        result["physics_cpu_gpu_comparison"] = {
            "status": "pass",
            "method": "byte-identical source integration state archives for identical scientific parameters; renderer never integrates",
        }
    path = ROOT / "reports" / ("V06_RENDER_GPU.json" if args.gpu else "V06_RENDER_CPU.json")
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
