import json

import numpy as np
import pytest
from pydantic import ValidationError

from human_models_mcp.registry import ContactParameters, AssistedContactParameters, discover


def test_contact_schemas_are_bounded_and_model_specific():
    scenarios = {s['id']: s for s in discover()['scenarios']}
    for name in ('standing_contact_probe', 'assisted_stance'):
        assert scenarios[name]['model'] == 'ms_human_700_locomotion'
        assert scenarios[name]['method'] == 'dynamic_forward'
    for bad in ({'duration_s': 60.0}, {'downward_load_N': 10000.0}, {'initial_velocity_x_m_per_s': float('nan')},
                {'steps': 400}, {'assistance': 'hidden_weld'}, {'command': 'echo unsafe'}):
        with pytest.raises(ValidationError):
            ContactParameters.model_validate(bad)
    with pytest.raises(ValidationError):
        AssistedContactParameters(assist_gain_scale=0.0)
    assert AssistedContactParameters(steps=400, timestep_s=.001).duration_s == .4


def test_contact_hull_and_degenerate_geometry():
    from human_models_mcp.adapters.contact import hull_xy, inside_hull
    points = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [.5, .5, 0]]
    hull, area = hull_xy(points)
    assert area == 1.0 and inside_hull([.5, .5], hull, area)
    assert not inside_hull([2, .5], hull, area)
    line, area = hull_xy([[0, 0, 0], [1, 0, 0]])
    assert area == 0 and not inside_hull([.5, 0], line, area)


def test_world_axis_initialization_and_declared_geometry():
    from human_models_mcp.adapters.contact import initialize
    mj, m, d, pelvis, floor, feet, initial = initialize(ContactParameters(render=False))
    assert m.nq == 36 and m.nu == 100 and m.neq == 16
    assert mj.mj_getTotalmass(m) == pytest.approx(60.21931681636449, abs=1e-12)
    assert len(feet) == 10 and d.ncon > 0
    vertical = next(s for s in initial['root_translation_adjustments'] if abs(s['world_axis'][2]) > .99)
    assert vertical['joint'] == 'pelvis_ty'
    assert min(mj.mj_geomDistance(m, d, i, floor, 1, None) for i in feet) == pytest.approx(.0002, abs=1e-12)
    assert not np.any(d.ctrl) and not np.any(d.xfrc_applied)


def test_real_contact_force_momentum_and_partial_checks(tmp_path):
    from human_models_mcp.adapters.contact import simulate_contact
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'standing_contact_probe')
    result = simulate_contact({'render': False}, tmp_path, scenario['validation'])
    assert result['status'] == 'computed'
    metrics = {m['name']: m['value'] for m in result['metrics']}
    assert metrics['max_force_residual_N'] < 1e-5 and metrics['max_moment_residual_Nm'] < 1e-5
    assert 0 < metrics['final_ground_reaction_z'] < metrics['model_weight']
    assert metrics['final_assist_force_z'] == 0 and metrics['external_assist_work'] == 0
    assert result['model_derivation']['added_equalities'] == 0
    assert json.loads((tmp_path/'contacts.json').read_text())['records'] > 0


@pytest.mark.parametrize('offset,phrase', [(-.02, 'penetration'), (.02, 'contacts absent')])
def test_initial_penetration_or_no_contact_is_not_success(tmp_path, offset, phrase):
    from human_models_mcp.adapters.contact import simulate_contact
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'standing_contact_probe')
    result = simulate_contact({'render': False, 'root_height_offset_m': offset}, tmp_path, scenario['validation'])
    assert result['status'] == 'invalid_input' and phrase in result['error']['message']
    assert not (tmp_path/'trajectory.npz').exists()


def test_world_orientation_feedback_has_correct_axes():
    from human_models_mcp.adapters.contact import controller, initialize
    mj, m, d, pelvis, _, _, _ = initialize(AssistedContactParameters(render=False))
    target = d.xquat[pelvis].copy()
    # A world-y rotation must produce corrective world-y torque despite the source's rotated pelvis frame.
    rot = np.array([np.cos(.05), 0, np.sin(.05), 0])
    actual = np.empty(4)
    mj.mju_mulQuat(actual, rot, target)
    d.xquat[pelvis] = actual
    matrix = np.empty(9)
    mj.mju_quat2Mat(matrix, actual)
    d.xmat[pelvis] = matrix
    _, torque, _, _ = controller(mj, m, d, pelvis, d.xipos[pelvis].copy(), target, 1)
    np.testing.assert_allclose(torque, [0, -100, 0], atol=1e-10)


def test_failed_named_check_preserves_partial_numeric_files(tmp_path):
    from copy import deepcopy
    from human_models_mcp.adapters.contact import simulate_contact
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'standing_contact_probe')
    validation = deepcopy(scenario['validation'])
    validation['checks']['force_balance_tolerance_N'] = 1e-18
    result = simulate_contact({'render': False}, tmp_path, validation)
    assert result['status'] == 'failed' and 'check failed' in result['error']['message']
    summary = json.loads((tmp_path/'summary.json').read_text())
    assert summary['status'] == 'partial' and len(summary['rows']) >= 1
    assert (tmp_path/'trajectory.npz').is_file() and not (tmp_path/'pose.png').exists()


def test_real_fresh_client_handles_unrequested_render(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from human_models_mcp.registry import home
    for name in ('models', 'models.lock.json', 'requirements.lock', 'runtime-environment.json', 'benchmarks', 'docs'):
        (tmp_path/name).symlink_to(home()/name)
    folder = tmp_path/'scenarios/standing_contact_probe'
    shutil.copytree(home()/'scenarios/standing_contact_probe', folder)
    path = folder/'scenario.yaml'
    path.write_text(path.read_text().replace('render: true', 'render: false'))
    output = tmp_path/'client.json'
    p = subprocess.run([sys.executable, str(home()/'examples/mcp-client/client.py'), '--scenario', 'standing_contact_probe', '--output', str(output)],
        env={**os.environ, 'HUMAN_MODELS_HOME': str(tmp_path)}, capture_output=True, text=True, timeout=90)
    assert p.returncode == 0, p.stderr+p.stdout
    result = json.loads(output.read_text())
    assert result['run']['status'] == 'computed' and result['png'] is None and result['motion'] is None


def test_connector_generation_uses_current_bundle_location(tmp_path):
    import shutil
    import subprocess
    import sys
    import tomllib
    from human_models_mcp.registry import home
    script = tmp_path/'scripts/print_client_config.py'
    script.parent.mkdir()
    shutil.copy2(home()/'scripts/print_client_config.py', script)
    output = subprocess.check_output([sys.executable, str(script)], cwd='/tmp', text=True)
    config = tomllib.loads(output)['mcp_servers']['human_models']
    assert config['args'][2] == str(tmp_path/'compose.yaml') and config['cwd'] == str(tmp_path)
    assert str(home()) not in output


def test_offline_export_cannot_mount_outside_project(tmp_path, monkeypatch):
    import runpy
    import sys
    from human_models_mcp.registry import home
    main = runpy.run_path(str(home()/'scripts/experiment.py'))['main']
    monkeypatch.setitem(main.__globals__, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['experiment', '--output', str(tmp_path.parent/'outside-export')])
    with pytest.raises(ValueError, match='inside this project'):
        main()


def test_contact_candidates_and_loaded_support_are_distinguished(tmp_path):
    from human_models_mcp.adapters.contact import simulate_contact
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'standing_contact_probe')
    result = simulate_contact({'render': False}, tmp_path, scenario['validation'])
    assert result['status'] == 'computed'
    rows = json.loads((tmp_path/'summary.json').read_text())['rows']
    assert rows[0]['floor_contact_count'] >= 2
    assert max(r['force_bearing_floor_contact_count'] for r in rows) >= 2
    assert any(c['name'] == 'bilateral_force_bearing_support_observed' for c in result['checks'])
