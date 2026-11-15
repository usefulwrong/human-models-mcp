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


def test_public_demo_detects_changed_bytes_and_private_data_without_echoing(tmp_path):
    demo = tmp_path / 'docs/demo'
    demo.mkdir(parents=True)
    (demo / 'preview.png').write_bytes(b'original')
    (demo / 'assets.json').write_text(json.dumps({'files': {'preview.png': {
        'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}}}))
    # Construct examples so the checker does not mistake its own test source for a leak.
    private_path = '/' + 'home' + '/example/project/'
    (tmp_path / 'README.md').write_text(private_path)
    assert any(f['reason'] == 'personal_path' for f in CHECK.check(tmp_path)['failures'])
    (tmp_path / 'README.md').write_text('[demo](docs/demo/preview.png)')
    assert CHECK.check(tmp_path)['status'] == 'pass'
    (demo / 'preview.png').write_bytes(b'changed!')
    assert any(f['reason'] == 'demo size/hash mismatch' for f in CHECK.check(tmp_path)['failures'])


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
