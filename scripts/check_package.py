import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
for name in ("LICENSE", "CITATION.cff", "notices/MS-Human-700-LICENSE", "notices/THIRD_PARTY.md"):
    assert (ROOT / name).is_file(), name
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
with tempfile.TemporaryDirectory() as temp:
    project = Path(temp)
    for name in (
        "src",
        "scenarios",
        "skills",
        "docs",
        "scripts",
        "examples",
        "tests",
        "notices",
        "benchmarks",
        ".github",
    ):
        shutil.copytree(
            ROOT / name, project / name, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
        )
    for name in (
        "pyproject.toml",
        "README.md",
        "AGENTS.md",
        "LICENSE",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "requirements.in",
        "requirements.lock",
        "models.lock.json",
        "MANIFEST.in",
        "Makefile",
        "Dockerfile",
        "compose.yaml",
        ".dockerignore",
        "Dockerfile.render",
        "Dockerfile.render.dockerignore",
        "compose.render-gpu.yaml",
        "renderer.lock.json",
        "requirements-render.lock",
        "visual_sources.json",
    ):
        shutil.copy2(ROOT / name, project / name)
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", str(project)],
        check=True,
        env={**os.environ, "PIP_NO_INDEX": "1"},
    )
    with tarfile.open(next((project / "dist").glob("*.tar.gz"))) as source:
        members = source.getnames()
        assert not any(p.endswith((".zip", ".mp4", ".gif", ".blend", ".usdc", ".obj")) for p in members)
        assert not any('/outputs/' in p or '/reports/' in p or '/render_vendor/' in p for p in members)
        assert next((project / "dist").glob("*.tar.gz")).stat().st_size < 2 * 1024 * 1024
        assert any(p.endswith("/scenarios/knee_sweep/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/knee_coupled/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/loaded_elbow/scenario.yaml") for p in members)
        assert any(p.endswith("/benchmarks/nichols2016_wrist/article.xml") for p in members)
        assert any(p.endswith("/scenarios/wrist_benchmark/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/elbow_tracking/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/standing_contact_probe/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/assisted_stance/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/pushup/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/pushup_palms/scenario.yaml") for p in members)
        assert any(p.endswith("/scenarios/pushup_knuckles/scenario.yaml") for p in members)
        assert any(p.endswith("/docs/HAND_DETAIL.md") for p in members)
        assert any(p.endswith("/AGENTS.md") for p in members)
        assert any(p.endswith("/tests/fixtures/rejected_knuckle_pose.json") for p in members)
        assert any(p.endswith("/adapters/palms_full_reference_v1.json") for p in members)
        assert any(p.endswith("/atlas_pectoralis.json") for p in members)
        assert any(p.endswith("/renderer.lock.json") for p in members)
        assert any(p.endswith("/skills/scientific-visualization/SKILL.md") for p in members)
    wheel = next((project / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel) as package:
        assert "human_models_mcp/server.py" in package.namelist()
        assert "human_models_mcp/adapters/contact.py" in package.namelist()
        assert "human_models_mcp/adapters/pushup.py" in package.namelist()
        assert "human_models_mcp/adapters/hands.py" in package.namelist()
        assert "human_models_mcp/adapters/pectorals.py" in package.namelist()
        assert "human_models_mcp/adapters/supports.py" in package.namelist()
        assert "human_models_mcp/adapters/palms_full_reference_v1.json" in package.namelist()
        assert "human_models_mcp/anatomy.py" in package.namelist()
        assert "human_models_mcp/atlas_pectoralis.json" in package.namelist()
        assert not any(name.endswith(".obj") for name in package.namelist())
        assert "human_models_mcp/rendering.py" in package.namelist()
        assert "human_models_mcp/blender_scene.py" in package.namelist()
        package.extractall(project / "installed")
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys;sys.path.insert(0,sys.argv[1]);from human_models_mcp import __version__;assert __version__==sys.argv[2]",
            str(project / "installed"),
            VERSION,
        ],
        cwd="/tmp",
        check=True,
    )
    destination = ROOT / "reports/packages" / VERSION
    destination.mkdir(parents=True, exist_ok=True)
    for artifact in (project / "dist").iterdir():
        shutil.copy2(artifact, destination / artifact.name)
print("Package wheel/sdist, dependency consistency, clean import and required notices: pass")
