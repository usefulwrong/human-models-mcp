"""Provision and run the local Human Models MCP checkout."""

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from uuid import uuid4
import webbrowser
import zipfile

from human_models_mcp.runtime.graphics import requested_backend
from human_models_mcp.runtime.locking import file_lock
from human_models_mcp.runtime.paths import flat_name, is_link, replace
from human_models_mcp.runtime.processes import managed_process

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
SERVICES = {"renderer": ["-m", "human_models_mcp.render_worker"],
            "explorer": [str(ROOT / "scripts/anatomy_lab/lab_web.py")],
            "http": ["-m", "human_models_mcp", "--transport", "http"]}
LOCKS = {
    "core": "requirements-windows-x64.lock",
    "renderer": "requirements-render-windows-x64.lock",
    "development": "requirements-dev-windows-x64.lock",
}
BUDGETS = {"core": (125, 1024), "explorer": (1800, 5500), "renderer": (530, 2500), "development": (85, 220)}


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pins():
    return (json_file(ROOT / "dependencies-windows-x64.json")
            | json_file(ROOT / "renderer.lock.json")["windows_x64"])


def safe_directory(path):
    if any(is_link(p) for p in (path, *path.parents)):
        raise ValueError(f"junction or symlink in installation directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def archive(item, cache, offline):
    name = item["url"].rsplit("/", 1)[-1]
    path = cache / name
    if is_link(path):
        raise ValueError(f"cache asset is a junction or symlink: {name}")
    if path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]:
        return path
    if offline:
        raise ValueError(f"missing or damaged offline asset: {name}")
    temporary = cache / f".{name}.{uuid4().hex}.part"
    print(f"Downloading {name} ({item['bytes'] / 1_000_000:.1f} MB)", flush=True)
    try:
        with urlopen(item["url"], timeout=120) as source, temporary.open("xb") as target:
            remaining = item["bytes"]
            while remaining:
                piece = source.read(min(1024**2, remaining))
                if not piece:
                    break
                target.write(piece)
                remaining -= len(piece)
            if remaining or source.read(1):
                raise ValueError(f"locked size differs: {name}")
        if sha(temporary) != item["sha256"]:
            raise ValueError(f"locked SHA-256 differs: {name}")
        replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def exec_checked(command, *, env=None, timeout=3600):
    result = subprocess.run(command, cwd=ROOT, env=env, timeout=timeout)
    result.check_returncode()


def install_wheels(component, cache, offline, prepare):
    lock = str(ROOT / LOCKS[component])
    args = [sys.executable, "-X", "utf8", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    flags = ["--require-hashes", "--only-binary=:all:", "-r", lock]
    if not offline:
        exec_checked([*args, "download", "--no-deps", "--dest", str(cache), *flags])
    if not prepare:
        exec_checked([*args, "install", "--force-reinstall", "--no-deps", "--no-index", "--no-cache-dir",
                      "--no-warn-script-location", "--find-links", str(cache), *flags])
        exec_checked([*args, "check"])


def install_cpp_runtime(item, cache, offline, prepare):
    source = archive(item, cache, offline)
    if prepare:
        return
    target = Path(sys.executable).parent
    with zipfile.ZipFile(source) as bundle:
        for name, expected in item["files"].items():
            if not flat_name(name) or not name.startswith("msvcp140") or not name.endswith(".dll"):
                raise ValueError("unexpected C++ runtime member")
            data = bundle.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"pinned C++ runtime member changed: {name}")
            path = target / name
            if is_link(path):
                raise ValueError(f"linked C++ runtime file: {name}")
            if not path.is_file() or sha(path) != expected:
                staged = target / f".{name}.{uuid4().hex}.part"
                try:
                    staged.write_bytes(data)
                    replace(staged, path)
                finally:
                    staged.unlink(missing_ok=True)


def unpack_vendor(key, item, cache, offline, prepare):
    source = archive(item, cache, offline)
    if prepare:
        return
    target = RUNTIME / "vendor" / key
    receipt = target / ".archive-sha256"
    if receipt.is_file() and receipt.read_text(encoding="utf-8") == item["sha256"]:
        return
    if target.exists() or is_link(target):
        raise ValueError(f"move damaged private runtime folder aside before reinstalling: {target}")
    safe_directory(target.parent)
    stage_parent = target.parent
    if os.name == "nt":
        # Windows Setup may leave the system-wide long-path policy disabled.
        local = str(stage_parent)
        prefix = "\\\\?\\"
        if not local.startswith(prefix):
            stage_parent = Path(prefix + ("UNC\\" + local[2:] if local.startswith("\\\\") else local))
    with tempfile.TemporaryDirectory(dir=stage_parent) as temp:
        stage = Path(temp)
        with zipfile.ZipFile(source) as bundle:
            seen = set()
            for entry in bundle.infolist():
                parts = entry.filename.rstrip("/").split("/")
                normalized = "/".join(parts).casefold()
                if (not all(map(flat_name, parts)) or normalized in seen
                        or entry.external_attr >> 28 == 0xA):
                    raise ValueError(f"invalid vendor archive entry: {entry.filename}")
                seen.add(normalized)
            bundle.extractall(stage)
        roots = list(stage.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError(f"unexpected {key} archive layout")
        (roots[0] / ".archive-sha256").write_text(item["sha256"], encoding="utf-8")
        roots[0].rename(target)


def explorer_env():
    root = Path(os.environ.get("HMM_LAB_INSTALL", ROOT / "outputs/anatomy-explorer")).resolve()
    settings = RUNTIME / "anatomy-motion.json"
    result = {**(json_file(settings) if settings.is_file() else {}), **os.environ}
    result.setdefault("HMM_LAB_CATALOG", str(root / "catalog.json"))
    result.setdefault("HMM_LAB_SITE", str(root / "site"))
    return result


def attach_motion(args):
    sys.path.insert(0, str(ROOT / "scripts/anatomy_lab"))
    from human_models_mcp.rendering import write_json
    from human_models_mcp.results import store
    from moving_transport import WholeMotion
    from anatomy_lab import Registry

    static = args.atlas.resolve() if args.atlas else ROOT / "outputs/anatomy-explorer"
    site = static / "site"
    if not (site / "index.html").is_file():
        raise ValueError("install Anatomy Explorer or specify its existing installation")
    scene = args.scene.resolve()
    results = store().resolve()
    atlas = Registry(static / "catalog.json", static / "meshes", site=site)
    whole = WholeMotion(scene, args.sha256, results, atlas.atlas_sha256, args.render_sha256)
    whole.verified()
    settings = {"HMM_LAB_CATALOG": str(static / "catalog.json"), "HMM_LAB_SITE": str(site),
                "HMM_LAB_WHOLE": str(scene), "HMM_LAB_WHOLE_SHA": args.sha256,
                "HMM_LAB_WHOLE_RESULTS": str(results)}
    if args.render_sha256:
        settings["HMM_LAB_WHOLE_RENDER_SHA"] = args.render_sha256
    if args.crosswalk:
        crosswalk = args.crosswalk.resolve()
        if is_link(crosswalk) or not crosswalk.is_file() or sha(crosswalk) != args.crosswalk_sha256:
            raise ValueError("the local crosswalk must match its supplied SHA-256")
        tool = ROOT / "scripts/muscle_intelligence/stage.py"
        app = RUNTIME / "muscle-explorer"
        if not app.is_dir():
            exec_checked([sys.executable, "-X", "utf8", str(tool), str(app), "--assets", str(site)])
        settings.update(HMM_LAB_APP=str(app / "lab"), HMM_LAB_SITE=str(app / "lab/site"),
                        HMM_LAB_MUSCLE_CROSSWALK=str(crosswalk),
                        HMM_LAB_MUSCLE_CROSSWALK_SHA=args.crosswalk_sha256)
    safe_directory(RUNTIME)
    write_json(RUNTIME / "anatomy-motion.json", settings)
    print("Verified MotionScene is attached. Restart the Explorer to open it.")


def renderer_env():
    env = dict(os.environ)
    if os.name == "nt":
        env.setdefault("BLENDER_BIN", str(RUNTIME / "vendor/blender/blender.exe"))
        env.setdefault("HMM_FFMPEG", str(RUNTIME / "vendor/ffmpeg/bin/ffmpeg.exe"))
        env.setdefault("HMM_RENDER_ENVIRONMENT", str(RUNTIME / "renderer-environment.json"))
    return env


def wheel_versions(component):
    return dict(line.split()[0].split("==") for line in (ROOT / LOCKS[component]).read_text(
        encoding="utf-8").splitlines() if line and not line.startswith("#"))


def dependency_errors(component):
    errors = []
    for name, version in wheel_versions(component).items():
        try:
            current = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            current = "missing"
        if current != version:
            errors.append(f"{name} is {current}; expected {version}")
    return errors


def windows_provisioning_tls():
    try:
        import truststore
    except ModuleNotFoundError:
        # Before Core is installed, the pinned pip archive supplies a CA bundle.
        from pip._vendor import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    else:
        truststore.inject_into_ssl()


def install_component(component, cache, *, offline, prepare):
    if os.name != "nt" or platform.machine() != "AMD64" or sys.version_info[:2] != (3, 12):
        raise ValueError("use the Windows x64 portable Python runtime from Install.cmd")
    if component != "core" and not prepare and dependency_errors("core"):
        raise ValueError("install Core before adding this component")
    if not offline:
        windows_provisioning_tls()
    items = pins()
    if component == "core":
        from provision import provision
        for key in ("python", "pip"):
            archive(items[key], cache, offline)
        install_cpp_runtime(items["vc_runtime"], cache, offline, prepare)
        install_wheels(component, cache, offline, prepare)
        if prepare:
            provision(cache / "models", offline=offline)
        else:
            provision(ROOT / "models", cache=cache / "models", offline=offline)
            from human_models_mcp.catalog import model_card
            from human_models_mcp.core import worker
            if model_card(verify=True)["status"] != "available":
                raise RuntimeError("pinned model verification failed")
            result = worker({"operation": "inspect", "model_id": "ms_human_700"})
            if result.get("status") != "computed" or result.get("actuators") != 700:
                raise RuntimeError(f"MuJoCo smoke test failed: {result}")
            from capture_environment import capture
            capture(ROOT, ROOT / "runtime-environment.json")
    elif component == "development":
        install_wheels(component, cache, offline, prepare)
    elif component == "renderer":
        for key in ("blender", "ffmpeg"):
            unpack_vendor(key, items[key], cache, offline, prepare)
        archive(items["usd_core"], cache, offline)
        install_wheels(component, cache, offline, prepare)
        if not prepare:
            env = renderer_env()
            for tool in (env["BLENDER_BIN"], env["HMM_FFMPEG"], str(RUNTIME / "vendor/ffmpeg/bin/ffprobe.exe")):
                arguments = ["-b", "--version"] if Path(tool).stem == "blender" else ["-version"]
                with managed_process([tool, *arguments], memory=8 * 1024**3, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                     errors="replace") as probe:
                    output, _ = probe.communicate(timeout=120)
                    if probe.returncode:
                        raise RuntimeError(f"{Path(tool).name} probe exited {probe.returncode}: {output[-500:]}")
                    print(output, end="")
            from capture_environment import capture
            capture(ROOT, RUNTIME / "renderer-environment.json")
    elif component == "explorer":
        unpack_vendor("node", items["node"], cache, offline, prepare)
        # The licensed upstream/cache workflow remains owned by the Anatomy Lab installer.
        from provision_anatomy import install as anatomy_install
        anatomy_install(ROOT, RUNTIME, cache, {"HMM_LAB_SITE":
                           str(ROOT / "outputs/anatomy-explorer/site")}, offline, prepare)


def install(args):
    if args.prepare and args.offline:
        raise ValueError("preparing a cache requires its pinned upstream sources")
    cache = Path(args.cache or os.environ.get("HMM_OFFLINE_CACHE") or RUNTIME / "cache").absolute()
    offline = args.offline or bool(os.environ.get("HMM_OFFLINE_CACHE"))
    if args.prepare and offline:
        raise ValueError("preparation requires an online cache")
    safe_directory(RUNTIME)
    safe_directory(cache)
    components = args.components or ["core"]
    if set(components) - set(BUDGETS):
        raise ValueError("components must be core, explorer, renderer or development")
    if "core" in components:
        components = ["core", *(part for part in components if part != "core")]
    download, needed = (sum(BUDGETS[part][n] for part in components) for n in range(2))
    print(f"Components: {', '.join(components)}. Allow about {download} MB download and {needed} MB disk.")
    if shutil.disk_usage(RUNTIME).free < needed * 1024**2:
        raise OSError(f"less than {needed} MiB free in the runtime directory")
    if not args.yes and input("Continue [y/N]? ").strip().lower() != "y":
        return
    with file_lock(RUNTIME / "install.lock", blocking=False) as acquired:
        if not acquired:
            raise RuntimeError("another installation is in progress")
        for component in components:
            state = RUNTIME / f"{component}.json"
            desired = {name: sha(ROOT / name) for name in (
                "dependencies-windows-x64.json", "models.lock.json", "renderer.lock.json", *LOCKS.values()
            )}
            if not args.prepare and not args.repair and state.is_file() and json_file(state) == desired:
                print(f"{component} is already installed. Run Doctor.cmd to check it.")
                continue
            log = RUNTIME / "install.log"
            with log.open("ab") as stream:
                stream.write(f"\n{datetime.now(timezone.utc).isoformat()} {component}\n".encode())
                env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
                proc = subprocess.Popen(
                    [sys.executable, "-X", "utf8", __file__, "_install", component, str(cache),
                     str(int(offline)), str(int(args.prepare))],
                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                try:
                    for line in proc.stdout:
                        stream.write(line)
                        stream.flush()
                        print(line.decode("utf-8", "replace").rstrip(), flush=True)
                    if proc.wait():
                        raise RuntimeError(f"installation failed for {component}; see {log}")
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    proc.wait()
            if not args.prepare:
                from human_models_mcp.rendering import write_json
                write_json(state, desired)


def diagnostics(probe, image=None):
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "available_disk_bytes": shutil.disk_usage(ROOT).free, "backend_requested": requested_backend()}
    try:
        from human_models_mcp.catalog import model_card
        from human_models_mcp.core import worker
        result["model"] = model_card(verify=True)["status"]
        if probe and result["model"] == "available":
            destination = (image or ROOT / "reports" / "graphics-probe").resolve()
            safe_directory(destination)
            result["probe"] = worker({"operation": "graphics_probe", "output": str(destination)})
            if result["probe"]["status"] == "rendered":
                result["probe"]["image"] = str(destination / "pose.png")
    except (ImportError, OSError, ValueError) as exc:
        result["error"] = str(exc)
    if os.name == "nt":
        errors = dependency_errors("core")
        for name, expected in pins()["vc_runtime"]["files"].items():
            path = Path(sys.executable).with_name(name)
            if is_link(path) or not path.is_file() or sha(path) != expected:
                errors.append(f"C++ runtime member absent or damaged: {name}")
        result["core_dependency_errors"] = errors
        result["renderer_installed"] = Path(renderer_env()["BLENDER_BIN"]).is_file()
    result["explorer_catalog"] = Path(explorer_env()["HMM_LAB_CATALOG"]).is_file()
    print(json.dumps(result, indent=2))
    return int(result.get("model") != "available" or bool(result.get("core_dependency_errors")))


def service(name):
    directory = RUNTIME / "services"
    safe_directory(directory)
    lock = directory / f"{name}.lock"
    stop = directory / f"{name}.stop"
    with file_lock(lock, blocking=False) as acquired:
        if not acquired:
            raise RuntimeError(f"{name} is already running")
        stop.unlink(missing_ok=True)
        env = renderer_env() if name == "renderer" else explorer_env()
        command = SERVICES[name]
        if name == "explorer" and env.get("HMM_LAB_APP"):
            command = ["-c",
                       "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('lab_web',run_name='__main__')",
                       env["HMM_LAB_APP"]]
        with managed_process([sys.executable, "-X", "utf8", *command], memory=10 * 1024**3,
                             linux_group=True, env=env, stdin=subprocess.DEVNULL) as process:
            while process.poll() is None and not stop.exists():
                time.sleep(.25)
            if process.returncode:
                raise RuntimeError(f"{name} exited {process.returncode}")
        stop.unlink(missing_ok=True)


def start_service(name):
    if name == "explorer" and not Path(explorer_env()["HMM_LAB_CATALOG"]).is_file():
        raise ValueError("install Anatomy Explorer using Install.cmd explorer")
    if name == "renderer" and os.name == "nt":
        if not Path(renderer_env()["BLENDER_BIN"]).is_file() or dependency_errors("renderer"):
            raise ValueError("install Renderer using Install.cmd renderer")
    directory = RUNTIME / "services"
    safe_directory(directory)
    lock, log_path = (directory / f"{name}.{extension}" for extension in ("lock", "log"))
    with file_lock(lock, blocking=False) as idle:
        if not idle:
            return
    port = {"http": 8765, "explorer": 8766}.get(name)
    if port is not None:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"local port {port} is already in use") from exc
    with log_path.open("ab") as log:
        process = subprocess.Popen([sys.executable, "-X", "utf8", __file__, "service", name],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    deadline = time.monotonic() + 45
    while process.poll() is None and time.monotonic() < deadline:
        if port is None:
            with file_lock(lock, blocking=False) as idle:
                if not idle:
                    return
        else:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.25):
                    return
            except OSError:
                pass
        time.sleep(.25)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    raise RuntimeError(f"{name} failed to start; see {log_path}")


def stop_services():
    directory = RUNTIME / "services"
    if not directory.is_dir():
        return
    active = []
    for name in SERVICES:
        if (directory / f"{name}.lock").is_file():
            with file_lock(directory / f"{name}.lock", blocking=False) as acquired:
                if not acquired:
                    (directory / f"{name}.stop").touch()
                    active.append(name)
    for name in active:
        with file_lock(directory / f"{name}.lock"):
            print(f"Stopped {name}.")


def examine(scenario, parameters, output):
    from human_models_mcp.core import run_scenario
    from human_models_mcp.results import get_artifact

    if not isinstance(parameters, dict):
        raise ValueError("parameters must be a JSON object")
    from human_models_mcp.core import describe_scenario
    if describe_scenario(scenario).get("defaults", {}).get("render"):
        parameters.setdefault("render", False)
    run = run_scenario(scenario, parameters)
    if output and run["status"] == "computed":
        sys.path.insert(0, str(ROOT / "examples/mcp-client"))
        from artifacts import export_run
        import asyncio

        async def artifact(name, args):
            if name != "get_artifact":
                raise ValueError("unsupported export operation")
            return get_artifact(**args)

        asyncio.run(export_run(artifact, run, output))
    print(json.dumps(run, indent=2))
    return int(run["status"] != "computed")


def ensure_core(yes=False):
    if os.name == "nt" and not (RUNTIME / "core.json").is_file():
        install(argparse.Namespace(components=["core"], cache=None, offline=False,
                                   yes=yes or os.environ.get("HMM_BOOTSTRAP_APPROVED") == "1",
                                   repair=False, prepare=False))
        return (RUNTIME / "core.json").is_file()
    return True


def cli_menu():
    if not ensure_core():
        return 1
    actions = {
        "1": "Open Anatomy Explorer", "2": "Run first experiment", "3": "Run selected scenario",
        "4": "Start Blender renderer", "5": "Render saved experiment", "6": "Generate MCP configuration",
        "7": "Install optional components", "8": "Open results folder", "9": "Run diagnostics", "10": "Stop services",
    }
    while True:
        print("\nHuman Models MCP")
        for key, label in actions.items():
            print(f"  {key}. {label}")
        try:
            choice = input("Choose an action, or Enter to exit: ").strip()
            if not choice:
                return 0
            if choice == "1":
                if not Path(explorer_env()["HMM_LAB_CATALOG"]).is_file():
                    raise ValueError("Install Anatomy Explorer using option 7.")
                start_service("explorer")
                webbrowser.open("http://127.0.0.1:8766/")
            elif choice in {"2", "3"}:
                from human_models_mcp.registry import discover
                if choice == "3":
                    print(", ".join(item["id"] for item in discover()["scenarios"]))
                examine("elbow_sweep" if choice == "2" else input("Scenario: ").strip(), {}, None)
            elif choice == "4":
                start_service("renderer")
                print("Renderer service log: " + str(RUNTIME / "services/renderer.log"))
            elif choice == "5":
                render(input("Saved run UUID: ").strip(), None)
            elif choice == "6":
                config("native", "toml")
            elif choice == "7":
                print("Optional components: explorer, renderer, development")
                parts = input("Components, separated by spaces: ").lower().split()
                if not parts or set(parts) - set(BUDGETS):
                    raise ValueError("select one or more listed components")
                install(argparse.Namespace(components=parts, cache=None, offline=False, yes=False,
                                           repair=False, prepare=False))
            elif choice == "8":
                from human_models_mcp.results import store
                safe_directory(store())
                if os.name == "nt":
                    os.startfile(store())
                else:
                    webbrowser.open(store().as_uri())
            elif choice == "9":
                diagnostics(True)
            elif choice == "10":
                stop_services()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print(str(exc), file=sys.stderr)


def config(mode, form):
    from print_client_config import configuration
    print(configuration(mode, form), end="")


def render(run_id, destination):
    from human_models_mcp.visualize import main

    sys.argv = [sys.argv[0], "render", "--run-id", run_id, "--profile", "preview", "--device", "cpu"]
    if destination:
        sys.argv.extend(["--wait", "--output", str(destination)])
    return main()


def main():
    os.environ.setdefault("HUMAN_MODELS_HOME", str(ROOT))
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action")
    setup = sub.add_parser("install")
    setup.add_argument("components", nargs="*", metavar="COMPONENT")
    setup.add_argument("--yes", action="store_true")
    setup.add_argument("--offline", action="store_true")
    setup.add_argument("--cache", type=Path)
    setup.add_argument("--prepare", action="store_true")
    setup.add_argument("--repair", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--no-probe", action="store_true")
    doctor.add_argument("--image-directory", type=Path)
    run = sub.add_parser("run")
    run.add_argument("scenario")
    run.add_argument("--params", default="{}")
    run.add_argument("--output", type=Path)
    submit = sub.add_parser("render")
    submit.add_argument("run_id")
    submit.add_argument("--output", type=Path)
    first = sub.add_parser("first")
    first.add_argument("--yes", action="store_true")
    first.add_argument("--output", type=Path)
    out = sub.add_parser("config")
    out.add_argument("--mode", choices=["native", "anatomy", "docker"], default="native")
    out.add_argument("--format", choices=["toml", "json"], default="toml")
    for command in ("service", "start-service"):
        sub.add_parser(command).add_argument("name", choices=SERVICES)
    sub.add_parser("stop")
    sub.add_parser("anatomy-mcp")
    attach = sub.add_parser("attach-motion")
    attach.add_argument("scene", type=Path)
    attach.add_argument("--sha256", required=True)
    attach.add_argument("--atlas", type=Path)
    attach.add_argument("--render-sha256")
    attach.add_argument("--crosswalk", type=Path)
    attach.add_argument("--crosswalk-sha256")
    if len(sys.argv) == 6 and sys.argv[1] == "_install":
        install_component(sys.argv[2], Path(sys.argv[3]), offline=bool(int(sys.argv[4])),
                          prepare=bool(int(sys.argv[5])))
        return 0
    args = p.parse_args()
    if args.action == "install":
        install(args)
    elif args.action == "doctor":
        return diagnostics(not args.no_probe, args.image_directory)
    elif args.action == "run":
        return examine(args.scenario, json.loads(args.params), args.output)
    elif args.action == "first":
        return examine("elbow_sweep", {}, args.output) if ensure_core(args.yes) else 1
    elif args.action == "config":
        config(args.mode, args.format)
    elif args.action == "render":
        return render(args.run_id, args.output)
    elif args.action == "service":
        service(args.name)
    elif args.action == "start-service":
        start_service(args.name)
    elif args.action == "stop":
        stop_services()
    elif args.action == "attach-motion":
        attach_motion(args)
    elif args.action == "anatomy-mcp":
        os.environ.update(explorer_env())
        sys.path.insert(0, os.environ.get("HMM_LAB_APP", str(ROOT / "scripts/anatomy_lab")))
        from lab_mcp import mcp
        mcp.run()
    else:
        return cli_menu()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, EOFError, subprocess.SubprocessError) as exc:
        with redirect_stdout(sys.stderr):
            print(f"Human Models MCP: {exc or 'input ended'}")
        raise SystemExit(1)
