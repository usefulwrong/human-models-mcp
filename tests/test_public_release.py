"""Small release-boundary checks: no network or model provisioning required."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location('public_check', Path(__file__).resolve().parents[1] / 'scripts/public_check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_public_links_reject_ignored_targets_and_invalid_anchors(tmp_path):
    (tmp_path / 'README.md').write_text('[ok](docs/science.md#units) [missing](outputs/private.md) [bad](docs/science.md#absent)')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/science.md').write_text('# Units\n')
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'outputs/private.md').write_text('exists locally, not delivered')
    result = CHECK.check(tmp_path)
    assert [x['status'] for x in result['relative_links']] == ['pass', 'fail', 'fail']


def test_public_demo_detects_changed_bytes(tmp_path):
    demo = tmp_path / 'docs/demo'
    demo.mkdir(parents=True)
    (demo / 'preview.png').write_bytes(b'original')
    (demo / 'assets.json').write_text(json.dumps({'files': {'preview.png': {
        'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}}}))
    (tmp_path / 'README.md').write_text('[demo](docs/demo/preview.png)')
    assert CHECK.check(tmp_path)['status'] == 'pass'
    (demo / 'preview.png').write_bytes(b'changed!')
    assert any(f['reason'] == 'demo size/hash mismatch' for f in CHECK.check(tmp_path)['failures'])


@pytest.mark.parametrize("preview", ["workflow", "v09"])
def test_preview_manifest_is_checked_alongside_historical_manifest(tmp_path, preview):
    archive = tmp_path / "docs/demo"
    workflow = archive / preview
    workflow.mkdir(parents=True)
    (archive / "assets.json").write_text('{"files": {}}')
    assert any(f["path"] == f"docs/demo/{preview}/assets.json" for f in CHECK.check(tmp_path)["failures"])
    (workflow / "assets.json").write_text('{"files": {"animation.mp4": {"bytes": 1, "sha256": "bad"}}}')
    (workflow / "animation.mp4").write_bytes(b"a")
    assert any(f["path"] == f"docs/demo/{preview}/animation.mp4" and f["reason"] == "demo size/hash mismatch"
               for f in CHECK.check(tmp_path)["failures"])


@pytest.mark.parametrize('renderer', ['sha256:renderer', None])
def test_offline_bundle_pins_images_and_cannot_inherit_host_build_or_store(renderer):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('package_release', root / 'scripts/package_release.py')
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    record = package.offline_compose((root / 'compose.yaml').read_text(), 'sha256:science', renderer)
    restored = yaml.safe_load(yaml.safe_dump(record))
    assert ('renderer' in restored['services']) == (renderer is not None)
    for name, service in restored['services'].items():
        assert service['image'] == ('sha256:science' if name == 'runtime' else renderer)
        assert service['pull_policy'] == 'never' and 'build' not in service
        assert service['network_mode'] == 'none' and service['read_only']
        assert all('${' not in volume for volume in service['volumes'])
        assert service['volumes'][0].startswith('./results:')


def _demo_archive(tmp_path, payload, filename="data.zip"):
    import io
    import zipfile

    demo = tmp_path / "docs/demo"
    demo.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
    (demo / filename).write_bytes(payload)
    (demo / "assets.json").write_text(json.dumps({"files": {filename: {
        "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()
    }}}))
    (tmp_path / "README.md").write_text("# Release candidate\n")

def test_public_check_finds_traversal_and_duplicate_names_inside_zip(tmp_path):
    import io
    import zipfile

    buffer = io.BytesIO()
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name", category=UserWarning)
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../outside.txt", "private")
            archive.writestr("readme.txt", "one")
            archive.writestr("readme.txt", "two")
    _demo_archive(tmp_path, buffer.getvalue())
    result = CHECK.check(tmp_path)
    assert any(item["reason"] == "unsafe archive entry" for item in result["failures"])
    assert any(item["reason"] == "duplicate archive entry" for item in result["failures"])

def test_public_check_strict_tree_rejects_unlisted_files(tmp_path):
    demo = tmp_path / "docs/demo"
    demo.mkdir(parents=True)
    (demo / "assets.json").write_text('{"files": {}}')
    (tmp_path / "README.md").write_text("# Research preview\n")
    (tmp_path / "operator_notes.txt").write_text("Do not publish")
    report = tmp_path / "scripts/anatomy_lab/report_site/index.html.in"
    report.parent.mkdir(parents=True)
    report.write_text("Private report template")
    assert CHECK.check(tmp_path)["status"] == "pass"
    result = CHECK.check(tmp_path, strict_tree=True)
    assert any(item["reason"] == "unlisted public tree file" for item in result["failures"])
    assert any(item["path"] == report.relative_to(tmp_path).as_posix() for item in result["failures"])
