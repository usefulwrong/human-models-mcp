"""Independent public-client checks of native contacts, momentum, controls and restart."""

import io
import json
from pathlib import Path

import numpy as np

from v04_e2e import artifact_bytes, rows

ROOT = Path(__file__).resolve().parents[1]


def physical_velocity_momentum(mj, model, state, qpos, qvel, pelvis):
    state.qpos[:], state.qvel[:] = qpos, qvel
    mj.mj_kinematics(model, state)
    mj.mj_comPos(model, state)
    mj.mj_comVel(model, state)
    mj.mj_subtreeVel(model, state)
    return state.subtree_linvel[pelvis].copy(), state.subtree_angmom[pelvis].copy()


async def independent_native_checks(call, run, trace):
    import mujoco as mj
    recipe = json.loads(await artifact_bytes(call, run, 'model_recipe.json'))
    model = mj.MjModel.from_xml_path(str(ROOT/'models/ms_human_700/scene_locomotion.xml'))
    model.opt.timestep = recipe['timestep_override_s']
    model.opt.tolerance, model.opt.iterations = recipe['solver_tolerance'], recipe['solver_iterations']
    assert model.nq == 36 and model.nu == 100 and model.neq == 16
    assert np.all(model.eq_type == mj.mjtEq.mjEQ_JOINT) and recipe['added_equalities'] == 0
    saved = np.load(io.BytesIO(await artifact_bytes(call, run, 'trajectory.npz')), allow_pickle=False)
    units = json.loads(await artifact_bytes(call, run, 'trajectory_metadata.json'))
    assert len(units['coordinates']) == 36 and len(units['actuator_order']) == 100
    assert units['actuator_force_unit'] == 'N'
    assert {r['generalized_force_unit'] for r in units['coordinates']} == {'N', 'N*m'}
    assert saved['qpos'].shape == (len(trace), 36) and saved['qvel'].shape == (len(trace), 36)
    assert np.isfinite(saved['states']).all() and not np.any(saved['ctrl']) and not np.any(saved['act'])
    if recipe['controller'] is None and recipe['downward_load_N'] == 0:
        assert not np.any(saved['xfrc_applied']) and not np.any(saved['qfrc_applied'])
    metadata = json.loads(await artifact_bytes(call, run, 'contacts.json'))
    raw = []
    for filename in metadata['files']:
        raw.extend(json.loads(await artifact_bytes(call, run, filename)))
    assert len(raw) == metadata['records']
    data, probe = mj.MjData(model), mj.MjData(model)
    pelvis, floor = model.body('pelvis').id, model.geom('floor').id
    mass = float(mj.mj_getTotalmass(model))
    maximum_force, maximum_moment, maximum_restart = 0.0, 0.0, 0.0
    for index in (0, len(trace)//2, len(trace)-2):
        mj.mj_setState(model, data, saved['states'][index], int(saved['state_spec']))
        mj.mj_forward(model, data)
        np.testing.assert_array_equal(data.qpos, saved['qpos'][index])
        center = (model.body_mass[:, None]*data.xipos).sum(axis=0)/mass
        np.testing.assert_allclose(center, [float(trace[index][f'com_{a}_m']) for a in 'xyz'], atol=1e-12, rtol=0)
        force, moment = np.zeros(3), np.zeros(3)
        contact_rows = [c for c in raw if c['sample'] == index]
        assert len(contact_rows) == data.ncon
        for i, c in enumerate(data.contact):
            cf = np.zeros(6)
            mj.mj_contactForce(model, data, i, cf)
            world = c.frame.reshape(3, 3).T@cf[:3]
            np.testing.assert_allclose(world, contact_rows[i]['force_on_geom1_world_N'], atol=1e-6, rtol=0)
            np.testing.assert_allclose(c.frame.reshape(3, 3)@c.frame.reshape(3, 3).T, np.eye(3), atol=1e-12)
            g0, g1 = map(int, c.geom)
            assert (int(model.geom_contype[g0]) & int(model.geom_conaffinity[g1])) or (int(model.geom_contype[g1]) & int(model.geom_conaffinity[g0]))
            assert cf[0] >= -1e-9
            if floor in c.geom:
                sign = 1 if c.geom[0] == floor else -1
                assert sign*c.frame.reshape(3, 3)[0, 2] > .99
                fw, tw = sign*world, sign*c.frame.reshape(3, 3).T@cf[3:]
                force += fw
                moment += np.cross(c.pos-center, fw)+tw
        np.testing.assert_allclose(force, [float(trace[index][f'grf_{a}_N']) for a in 'xyz'], atol=1e-6, rtol=0)
        # A separate recursive body-velocity/momentum method, not the adapter's Jacobian derivative.
        h = 1e-6
        samples = []
        for sign in (-1, 1):
            pos = data.qpos.copy()
            mj.mj_integratePos(model, pos, data.qvel, sign*h)
            samples.append(physical_velocity_momentum(mj, model, probe, pos, data.qvel+sign*h*data.qacc, pelvis))
        acceleration = (samples[1][0]-samples[0][0])/(2*h)
        hdot = (samples[1][1]-samples[0][1])/(2*h)
        ext = data.xfrc_applied[pelvis]
        r_force = mass*acceleration-force-mass*model.opt.gravity-ext[:3]
        r_moment = hdot-moment-ext[3:]-np.cross(data.xipos[pelvis]-center, ext[:3])
        maximum_force = max(maximum_force, float(np.linalg.norm(r_force)))
        maximum_moment = max(maximum_moment, float(np.linalg.norm(r_moment)))
        assert maximum_force < 1e-5 and maximum_moment < 1e-5
        if recipe['controller']:
            control = recipe['controller']
            target = np.empty(9)
            mj.mju_quat2Mat(target, np.array(control['target_quaternion_wxyz']))
            relative = target.reshape(3, 3)@data.xmat[pelvis].reshape(3, 3).T
            angle = np.arccos(np.clip((np.trace(relative)-1)/2, -1, 1))
            skew = np.array([relative[2, 1]-relative[1, 2], relative[0, 2]-relative[2, 0], relative[1, 0]-relative[0, 1]])
            world_error = skew*.5 if angle < 1e-8 else skew*angle/(2*np.sin(angle))
            velocity = np.zeros(6)
            mj.mj_objectVelocity(model, data, mj.mjtObj.mjOBJ_BODY, pelvis, velocity, 0)
            scale = control['gain_scale']
            expected_force = np.clip(scale*(3000*(np.array(control['target_pelvis_com_world_m'])-data.xipos[pelvis])-300*velocity[3:])+[0, 0, .25*mass*9.81], -1000, 1000)
            expected_torque = np.clip(scale*(1000*world_error-100*velocity[:3]), -200, 200)
            np.testing.assert_allclose(expected_force, [float(trace[index][f'assist_force_{a}_N']) for a in 'xyz'], atol=1e-8)
            np.testing.assert_allclose(expected_torque, [float(trace[index][f'assist_torque_{a}_Nm']) for a in 'xyz'], atol=1e-8)
            expected_power = expected_force@velocity[3:]+expected_torque@velocity[:3]
            assert abs(expected_power-float(trace[index]['assist_power_W'])) < 1e-8
        mj.mj_step(model, data)
        difference = float(np.max(abs(data.qpos-saved['qpos'][index+1])))
        maximum_restart = max(maximum_restart, difference)
        assert difference < 1e-11
        np.testing.assert_allclose(data.qvel, saved['qvel'][index+1], atol=1e-10, rtol=0)
    return {'recursive_body_momentum_force_residual_N': maximum_force, 'recursive_body_momentum_moment_residual_Nm': maximum_moment,
            'maximum_restart_qpos_difference': maximum_restart, 'raw_contact_records_checked': len(raw)}


async def exercise_v05(call, label):
    models = await call('list_models')
    assert {'ms_human_700', 'ms_human_700_locomotion'} <= {m['id'] for m in models['models']}
    card = await call('describe_model', {'model_id': 'ms_human_700_locomotion'})
    assert card['status'] == 'available' and card['license'] == 'Apache-2.0' and len(card['source_files']) == 2
    assert (await call('get_joint_info', {'model_id': card['id']}))['nq'] == 36
    for quantity in ('standing_balance', 'pushup', 'running', 'breathing', 'defecation', 'sex_specific_anatomy', 'extreme_pose_safety'):
        response = await call('get_model_capabilities', {'model_id': card['id'], 'quantity': quantity})
        assert response['status'] == 'unsupported' and response['reason'] == 'known_unsupported'
    result = {}
    for scenario_id in ('standing_contact_probe', 'assisted_stance'):
        scenario = await call('describe_scenario', {'scenario_id': scenario_id})
        assert scenario['model'] == card['id'] and scenario['method'] == 'dynamic_forward'
        run = await call('run_scenario', {'scenario_id': scenario_id})
        assert run['status'] == 'computed', run
        assert run['model']['id'] == card['id'] and run['scientific']['numerical_status'] == 'validated_for_named_checks'
        assert run['scientific']['validation_level'] == 'numerical_sanity'
        assert run['execution']['physics_backend'] == 'cpu' and run['execution']['render_backend'] == 'osmesa'
        assert await call('get_result', {'run_id': run['run_id']}) == run
        trace = await rows(call, run)
        repeated = await call('run_scenario', {'scenario_id': scenario_id, 'parameters': {'render': False}})
        refined = await call('run_scenario', {'scenario_id': scenario_id, 'parameters': {'render': False, 'steps': scenario['defaults']['steps']*2, 'timestep_s': .001}})
        perturbed = await call('run_scenario', {'scenario_id': scenario_id, 'parameters': {'render': False, 'initial_velocity_x_m_per_s': .02}})
        assert repeated['status'] == refined['status'] == perturbed['status'] == 'computed', (repeated, refined, perturbed)
        assert trace == await rows(call, repeated)
        refined_rows = await rows(call, refined)
        distance = float(np.linalg.norm([float(trace[-1][f'com_{a}_m'])-float(refined_rows[-1][f'com_{a}_m']) for a in 'xyz']))
        assert distance < .001
        metrics = {m['name']: m['value'] for m in run['outputs']['metrics']}
        finer = {m['name']: m['value'] for m in refined['outputs']['metrics']}
        impulse_difference = abs(metrics['ground_vertical_impulse']-finer['ground_vertical_impulse'])
        assert impulse_difference < .5
        assert metrics['max_force_residual_N'] < 1e-5 and metrics['max_moment_residual_Nm'] < 1e-5
        assert metrics['max_penetration_m'] < .005 and metrics['model_mass'] > 0
        assert max(int(r['force_bearing_floor_contact_count']) for r in trace) >= 2
        if scenario_id == 'standing_contact_probe':
            assert metrics['final_assist_force_z'] == metrics['external_assist_work'] == 0
        else:
            assert abs(metrics['final_assist_force_z']) > 1 and run['execution']['controller']['type'] == 'pelvis_world_pd'
        times = [float(r['time_s']) for r in trace]
        work = sum(.5*(float(a['assist_power_W'])+float(b['assist_power_W']))*(tb-ta) for a, b, ta, tb in zip(trace, trace[1:], times, times[1:]))
        assert abs(work-metrics['external_assist_work']) < 1e-10
        for row in trace:
            for axis in 'xyz':
                balance = metrics['model_mass']*(float(row[f'com_acceleration_{axis}_m_per_s2'])+(9.81 if axis == 'z' else 0))-float(row[f'grf_{axis}_N'])-float(row[f'assist_force_{axis}_N'])
                assert abs(balance) < 1e-5
        independent = await independent_native_checks(call, run, trace)
        frame = json.loads(await artifact_bytes(call, run, 'frames.json'))
        archive = np.load(io.BytesIO(await artifact_bytes(call, run, 'trajectory.npz')), allow_pickle=False)
        assert len(frame['frames']) == 21 and frame['model_id'] == card['id']
        for item in frame['frames']:
            import hashlib
            from PIL import Image, ImageStat
            assert item['state_sha256'] == hashlib.sha256(archive['states'][item['state_index']].tobytes()).hexdigest()
            assert abs(item['time_s']-archive['time_s'][item['state_index']]) < 1e-12
            binary = await artifact_bytes(call, run, item['artifact_id'])
            with Image.open(io.BytesIO(binary)) as image:
                image.verify()
            with Image.open(io.BytesIO(binary)) as image:
                assert image.size == (640, 640) and max(ImageStat.Stat(image).stddev) > 1
        result[scenario_id] = {'run': run, 'repeat_run_id': repeated['run_id'], 'refined_run_id': refined['run_id'], 'perturbed_run_id': perturbed['run_id'],
                               'com_refinement_distance_m': distance, 'vertical_impulse_refinement_difference_Ns': impulse_difference,
                               'endpoint_grf_refinement_difference_N': abs(metrics['final_ground_reaction_z']-finer['final_ground_reaction_z']),
                               'independent_native_checks': independent,
                               'checks': ['source_model_scene', 'initial_bilateral_contact_candidates', 'force_bearing_support_observed', 'recursive_body_momentum_method', 'contact_frame_sign_and_rotation',
                                          'control_law_if_assisted', 'repeatability', 'timestep_refinement', 'initial_velocity_perturbation', 'support_work', 'native_restart', 'state_frame_hashes', 'real_pixels']}
    for parameters in ({'root_height_offset_m': -.02}, {'root_height_offset_m': .02}, {'downward_load_N': 10000.0}, {'duration_s': 10.0}):
        response = await call('run_scenario', {'scenario_id': 'standing_contact_probe', 'parameters': {**parameters, 'render': False}})
        assert response['status'] == 'invalid_input' and response['error']['message'] and not response.get('outputs', {}).get('metrics'), response
    for parameters in ({'assist_gain_scale': 0.0}, {'assistance': 'hidden_weld'}):
        response = await call('run_scenario', {'scenario_id': 'assisted_stance', 'parameters': parameters})
        assert response['status'] == 'invalid_input'
    loaded = await call('run_scenario', {'scenario_id': 'standing_contact_probe', 'parameters': {'render': False, 'downward_load_N': 50.0}})
    assert loaded['status'] == 'computed', loaded
    loaded_trace = await rows(call, loaded)
    mass = next(m['value'] for m in loaded['outputs']['metrics'] if m['name'] == 'model_mass')
    for row in loaded_trace:
        assert abs(mass*(float(row['com_acceleration_z_m_per_s2'])+9.81)-float(row['grf_z_N'])+50) < 1e-5
    result['load_test'] = {'run_id': loaded['run_id'], 'downward_load_N': 50.0, 'status': 'pass'}
    return result
