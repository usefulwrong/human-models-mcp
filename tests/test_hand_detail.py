import json

import numpy as np
import pytest

from human_models_mcp.adapters.hands import HAND_MUSCLES, measure_knuckle_technique, measure_palm_technique, measure_wrists, palm_placement_passes, wrist_shaft_extension
from human_models_mcp.adapters.pushup import anatomical_group, pushup_model, reference_poses, simulate_pushup
from human_models_mcp.anatomy import path_regions, selected_paths
from human_models_mcp.registry import PushupParameters, discover


def test_all_requested_native_regions_are_selected():
    _, model, _ = pushup_model()
    regions = path_regions(model)
    selected = selected_paths(model, ['muscle_paths'])
    assert len(selected) == 418
    for side in 'rl':
        for name in HAND_MUSCLES:
            assert 'hand_tendons' in selected[name + '_' + side]
        for name in ('BIClong', 'BICshort', 'BRA', 'TRIlong', 'TRImed', 'TRIlat'):
            assert 'arm_muscles' in selected[name + '_' + side]
    assert all('abdominal_muscles' in regions[n] for n in ('rect_abd_r', 'rect_abd_l', 'TR1_r', 'IO1_l', 'EO_R12_l'))
    assert all('lumbar_muscles' in regions[n] for n in ('QL_post_I_1-L3_r', 'MF_m1s_r', 'Ps_L5_VB_l'))
    assert anatomical_group('TR1_r') != 'trapezius'
    assert set(selected_paths(model, ['hand_tendons'])) <= set(selected)
    assert set(selected_paths(model, ['pectoral_muscles'])) == {f'PECM{i}_{s}' for i in (1, 2, 3) for s in 'rl'}


@pytest.mark.parametrize('support,pads_per_hand', [('palms', 3), ('knuckles', 2)])
def test_source_hands_keep_full_model_and_fixed_finger_poses(support, pads_per_hand):
    mj, original, _ = pushup_model()
    mj, model, data = pushup_model(hand_support=support)
    assert (model.nq, model.nu, model.neq, model.nbody) == (85, 700, 42, 81)
    assert abs(mj.mj_getTotalmass(model) - mj.mj_getTotalmass(original)) < 1e-10
    assert [model.actuator(i).name for i in range(700)] == [original.actuator(i).name for i in range(700)]
    for side in 'rl':
        assert sum(model.geom(i).name.startswith('palm_' + side) for i in range(model.ngeom)) == pads_per_hand
        assert sum(model.geom(i).name.startswith('hand_detail_' + side) and model.geom_type[i] == mj.mjtGeom.mjGEOM_MESH for i in range(model.ngeom)) == 23
    poses, _ = reference_poses(mj, model, data, support)
    initial = mj.MjData(model)
    mj.mj_resetDataKeyframe(model, initial, 0)
    first, _ = reference_poses(mj, model, initial, support, initial_only=True)
    assert np.array_equal(first[0], poses[0])
    for qpos in poses[[0, 8, 16]]:
        data.qpos[:] = qpos
        mj.mj_forward(model, data)
        values, details = measure_wrists(mj, model, data, support)
        assert all(h['ligament_forces'] is None for h in details)
        assert all(values[f'hand_{s}_support_tilt_rad'] < .002 for s in 'rl')


@pytest.mark.parametrize('support', ['palms', 'knuckles'])
def test_detailed_comparison_records_real_muscles_and_declared_assistance(tmp_path, support):
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'pushup_' + support)
    result = simulate_pushup(scenario['defaults'], tmp_path, scenario['validation'])
    assert result['acceptance']['full_pushup'] == 'PASS'
    if support == 'palms':
        assert result['acceptance']['full_cycle_kinematics'] == 'PASS'
        assert result['acceptance']['reference_hand_placement'] == 'PASS'
        assert result['acceptance']['elbow_extension'] == 'PASS'
        assert result['acceptance']['wrist_extension_envelope'] == 'PASS'
        assert result['acceptance']['wrist_range_derivation'] == 'LITERATURE_INFORMED_NOT_CALIBRATED'
        assert json.loads((tmp_path / 'summary.json').read_text())['metrics']['max_palm_shoulder_chest_gap_m'] < .05
    assert result['acceptance']['external_control'] == 'USED'
    assert result['acceptance']['muscle_driven'] == 'NOT_ACHIEVED'
    assert result['acceptance']['wrist_ligaments'] == 'NOT_MODELED'
    assert result['acceptance']['stationary_supports'] == 'PASS'
    params = scenario['defaults']
    mj, model, data = pushup_model(params['timestep_s'], params['friction'], hand_support=support,
        support_boundary=params['support_boundary'], knuckle_technique=params.get('knuckle_technique', 'legacy_flared'),
        palm_technique=params.get('palm_technique', 'legacy_reach'))
    if support == 'knuckles':
        assert all(result['acceptance'][n] == 'PASS' for n in ('neutral_knuckle_grip', 'tucked_elbows', 'bottom_depth'))
    archive = np.load(tmp_path / 'trajectory.npz')
    import csv
    pectorals = list(csv.DictReader((tmp_path / 'pectorals.csv').open()))
    assert len(pectorals) == 6 * len(archive['qpos'])
    assert json.loads((tmp_path / 'pectorals.json').read_text())['path_count'] == 6
    stationarity = json.loads((tmp_path / 'support_stationarity.json').read_text())
    assert set(stationarity['max_displacement_by_point_m']) == {'palm_r', 'palm_l', 'toe_r', 'toe_l'}
    assert max(stationarity['max_contact_patch_displacement_by_pad_m'].values()) < .0005
    assert max(np.ptp(archive['qpos'][:, model.jnt_qposadr[model.joint(n + '_r').id]])
               for n in ('flexion', 'deviation', 'pro_sup')) > .01
    pads = [i for i in range(model.ngeom) if model.geom(i).name.startswith(('palm_', 'toe_'))]
    mj.mj_setState(model, data, archive['states'][0], int(archive['state_spec']))
    mj.mj_forward(model, data)
    initial = data.geom_xpos[pads, :2].copy()
    for state in archive['states']:
        mj.mj_setState(model, data, state, int(archive['state_spec']))
        mj.mj_forward(model, data)
        assert np.max(np.linalg.norm(data.geom_xpos[pads, :2] - initial, axis=1)) < .0005
        if support == 'palms':
            assert palm_placement_passes([measure_palm_technique(model, data)])
            assert max(wrist_shaft_extension(model, data, s) for s in 'rl') <= np.pi / 2 + .01
    if support == 'palms':
        assert np.max(archive['qpos'][[0, -1]][:, [59, 79]]) < .15
        assert np.min(np.max(archive['qpos'][:, [59, 79]], axis=0)) > 1.8
        assert result['model_derivation']['ik']['reference_asset_sha256']
        assert (tmp_path / 'palm_reference_input.json').is_file()
    for index in (20, 60, 100):
        mj.mj_setState(model, data, archive['states'][index], int(archive['state_spec']))
        mj.mj_forward(model, data)
        assert not np.any(data.qfrc_applied[:6]) and not np.any(data.xfrc_applied)
        assert np.max(data.act) > .05 and np.max(abs(data.qfrc_actuator)) > 1
        for entry in (r for r in pectorals if int(r['sample']) == index):
            aid = model.actuator(entry['actuator']).id
            assert float(entry['force_N']) == pytest.approx(data.actuator_force[aid], abs=1e-8)
            assert float(entry['activation']) == data.act[model.actuator_actadr[aid]]
            assert float(entry['power_W']) == pytest.approx(data.actuator_force[aid] * data.actuator_velocity[aid], abs=1e-8)
        stored = json.loads((tmp_path / 'wrists.json').read_text())['samples'][index]['hands']
        _, actual = measure_wrists(mj, model, data, support)
        for a, b in zip(actual, stored, strict=True):
            assert np.allclose(a['force_world_N'], b['force_world_N'], rtol=0, atol=1e-8)
            assert np.allclose(a['ground_moment_about_wrist_Nm'], b['ground_moment_about_wrist_Nm'], rtol=0, atol=1e-8)
    assert max(p.stat().st_size for p in tmp_path.iterdir()) < 2 * 1024 * 1024


def test_hand_option_boundary_and_discovery():
    from pydantic import ValidationError
    from human_models_mcp.rendering import RenderOptions, list_render_profiles
    with pytest.raises(ValidationError):
        PushupParameters(hand_support='invented')
    with pytest.raises(ValidationError):
        PushupParameters(support_boundary='fixed_points')
    with pytest.raises(ValidationError):
        PushupParameters(knuckle_technique='neutral_tucked')
    with pytest.raises(ValidationError):
        PushupParameters(palm_technique='chest_level')
    with pytest.raises(ValidationError):
        PushupParameters(palm_technique='chest_full')
    with pytest.raises(ValidationError):
        RenderOptions(camera_view='custom_script')
    info = list_render_profiles()
    assert {'hand_tendons', 'arm_muscles', 'lumbar_muscles', 'abdominal_muscles', 'hand_contacts'} <= info['layers'].keys()
    assert 'wrist_ligaments' in info['unsupported_layers']


def test_full_palm_derivation_changes_only_two_declared_extension_bounds():
    mj, original, _ = pushup_model(hand_support='palms', support_boundary='fixed_points', palm_technique='chest_level')
    _, model, data = pushup_model(hand_support='palms', support_boundary='fixed_points', palm_technique='chest_full')
    changes = np.argwhere(original.jnt_range != model.jnt_range)
    assert changes.tolist() == [[model.joint('flexion_r').id, 0], [model.joint('flexion_l').id, 0]]
    for name in ('jnt_limited', 'actuator_gainprm', 'actuator_biasprm', 'actuator_dynprm', 'actuator_lengthrange', 'dof_damping'):
        assert np.array_equal(getattr(original, name), getattr(model, name))
    poses, info = reference_poses(mj, model, data, 'palms', palm_technique='chest_full')
    assert poses.shape == (33, 89) and info['max_support_closure_m'] < 1e-10
    for qpos in poses:
        data.qpos[:] = qpos
        mj.mj_forward(model, data)
        assert max(wrist_shaft_extension(model, data, s) for s in 'rl') < np.pi / 2
    for side in 'rl':
        model.jnt_range[model.joint('flexion_' + side).id, 0] = -.6
    with pytest.raises(ValueError, match='joint bound'):
        reference_poses(mj, model, data, 'palms', palm_technique='chest_full')
    assert original.key_qpos[0, original.joint('elbow_flexion_r').id] == pytest.approx(1.4, abs=1e-6)


def test_shaft_wrist_angle_is_invariant_under_world_rotation():
    mj, model, data = pushup_model(hand_support='palms', support_boundary='fixed_points', palm_technique='chest_full')
    mj.mj_forward(model, data)
    before = {s: wrist_shaft_extension(model, data, s) for s in 'rl'}
    data.qpos[4:6] += [.2, .3]
    mj.mj_forward(model, data)
    for side in 'rl':
        assert wrist_shaft_extension(model, data, side) == pytest.approx(before[side], abs=1e-12)


@pytest.mark.parametrize('support', ['palms', 'knuckles'])
def test_sticking_guides_preserve_free_vertical_contact_and_human_model(support):
    mj, base, _ = pushup_model(hand_support=support)
    mj, model, _ = pushup_model(hand_support=support, support_boundary='fixed_points', timestep_s=.0005)
    assert (model.nq, model.nv, model.nu, model.neq, model.nbody) == (89, 89, 700, 46, 85)
    assert model.body_subtreemass[model.body('pelvis').id] == pytest.approx(mj.mj_getTotalmass(base))
    for name in ('palm_r', 'palm_l', 'toe_r', 'toe_l'):
        joint = model.joint('support_height_' + name).id
        assert not model.jnt_limited[joint] and model.dof_armature[joint] == 0
        assert np.array_equal(model.jnt_axis[joint], [0, 0, 1])
        assert model.geom_contype[model.geom(name).id] != 0


def test_former_sliding_palms_fail_stationarity_instead_of_passing(tmp_path):
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'pushup_palms')
    result = simulate_pushup({**scenario['defaults'], 'support_boundary': 'frictional', 'palm_technique': 'legacy_reach'}, tmp_path, scenario['validation'])
    assert result['acceptance']['stationary_supports'] == 'FAIL'
    assert result['acceptance']['full_pushup'] == 'FAIL'
    assert json.loads((tmp_path / 'summary.json').read_text())['metrics']['max_support_slip_m'] > .01


def test_fixed_boundary_rejects_insufficient_floor_friction(tmp_path):
    scenario = next(s for s in discover()['scenarios'] if s['id'] == 'pushup_knuckles')
    result = simulate_pushup({**scenario['defaults'], 'friction': .05}, tmp_path, scenario['validation'])
    assert result['acceptance']['numerical_bounds'] == 'FAIL'
    assert result['acceptance']['full_pushup'] == 'FAIL'
    assert json.loads((tmp_path / 'summary.json').read_text())['metrics']['max_friction_violation_N'] > 1


def test_rejected_original_knuckle_pose_exposes_wrong_grip_and_joint_limits():
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/rejected_knuckle_pose.json').read_text())
    mj, model, data = pushup_model(timestep_s=.0005, hand_support='knuckles', support_boundary='fixed_points')
    data.qpos[:] = fixture['frames'][1]['qpos']
    mj.mj_forward(model, data)
    measured = measure_knuckle_technique(model, data)
    for side in 'rl':
        assert measured[f'hand_{side}_palm_inward_cosine'] < -.75
        assert measured[f'hand_{side}_radial_forward_cosine'] < -.75
        assert measured[f'elbow_{side}_flare_rad'] > np.deg2rad(60)
        assert measured[f'shoulder_{side}_above_elbow_m'] > .13
        joint = model.joint('pro_sup_' + side).id
        assert abs(data.qpos[joint] - model.jnt_range[joint, 1]) < .0001


def test_palm_placement_uses_supports_at_shoulders_or_chest_not_head():
    from pathlib import Path
    from human_models_mcp.adapters.supports import fixed_reference_poses
    fixture = json.loads((Path(__file__).parent / 'fixtures/palm_placement_poses.json').read_text())
    mj, model, data = pushup_model(**fixture['parameters'])
    with pytest.raises(ValueError, match='initial placement target'):
        fixed_reference_poses(mj, model, data, palm_level='shoulders')
    for pose, expected in zip(fixture['poses'], (False, True), strict=True):
        data.qpos[:] = pose['qpos']
        mj.mj_forward(model, data)
        row = measure_palm_technique(model, data)
        assert palm_placement_passes([row]) is expected
        if not expected:
            assert all(abs(row[f'hand_{s}_ahead_head_m']) < .05 for s in 'rl')
            assert all(row[f'palm_{s}_shoulder_chest_gap_m'] > .2 for s in 'rl')
    # Synthetic support positions test the chest/caudal boundary, not human dynamics.
    for s in 'rl':
        shift = -(row[f'palm_{s}_ahead_shoulder_m'] + row[f'palm_{s}_ahead_chest_caudal_m']) / 2
        for g in range(model.ngeom):
            if model.geom(g).name.startswith('palm_' + s):
                data.geom_xpos[g, 0] += shift
    chest = measure_palm_technique(model, data)
    assert palm_placement_passes([chest])
    assert all(chest[f'palm_{s}_ahead_shoulder_m'] < 0 < chest[f'palm_{s}_ahead_chest_caudal_m'] for s in 'rl')
    data.geom_xpos[model.geom('skull').id, 0] += 1
    assert palm_placement_passes([measure_palm_technique(model, data)])
    for g in range(model.ngeom):
        if model.geom(g).name.startswith('palm_'):
            data.geom_xpos[g, 0] -= .4
    assert not palm_placement_passes([measure_palm_technique(model, data)])
