import base64
import hashlib
from io import BytesIO
import json

import numpy as np
import pytest

from human_models_mcp.adapters.contact_geometry import FLOOR_BIT, contact_manifest, initial_floor_gap
from human_models_mcp.adapters.pushup import pushup_model
from human_models_mcp.contact_results import get_contact
from human_models_mcp.registry import PushupParameters


@pytest.mark.parametrize("profile", ["surface_spheres_v1", "surface_convex_v1"])
def test_floor_only_contact_preserves_native_mechanics(profile):
    config = {"hand_support": "palms", "palm_technique": "chest_full"}
    mj, base, _ = pushup_model(**config)
    _, model, data = pushup_model(**config, support_boundary="frictional_contact", contact_profile=profile)
    assert (model.nq, model.nv, model.nu, model.neq) == (85, 85, 700, 42)
    assert all(model.eq_type == mj.mjtEq.mjEQ_JOINT)
    assert not any(model.body(i).name.startswith("support_guide") for i in range(model.nbody))
    for name in ("body_mass", "body_inertia", "jnt_range", "actuator_gainprm", "actuator_biasprm"):
        np.testing.assert_array_equal(getattr(base, name), getattr(model, name))
    mj.mj_forward(model, data)
    mapping = contact_manifest(mj, model, data, profile)
    assert mapping["floor"]["conaffinity"] == FLOOR_BIT
    assert model.geom_contype[model.geom("palm_r").id] == 0
    for name in ("hand_detail_r_thumbdist", "hand_detail_l_2distph", "r_bofoot", "l_bofoot", "skull", "Sternum"):
        proxy, = mapping["visible_surfaces"][name]["collision_geoms"]
        assert mapping["collision_geoms"][proxy]["conaffinity"] == 0
    assert initial_floor_gap(mj, model, data) < -.015
    contacts = [(int(c.geom[0]), int(c.geom[1])) for c in data.contact if 0 in c.geom]
    assert contacts
    assert all(model.geom_contype[b if a == 0 else a] == FLOOR_BIT for a, b in contacts)


def test_parameter_and_result_boundaries(monkeypatch):
    with pytest.raises(ValueError):
        PushupParameters(contact_profile="surface_convex_v1")
    assert "contact_profile" not in PushupParameters().model_dump()
    assert get_contact("bad", "hand_l", 0, 1)["status"] == "invalid_input"
    assert get_contact("bad", "hand_l", 0, quantity="skin_contact_pressure")["measurement_status"] == "UNSUPPORTED"
    assert get_contact("bad", "hand_l", time_s=float("nan"))["status"] == "invalid_input"
    monkeypatch.setattr("human_models_mcp.contact_results.get_run", lambda _: {"artifacts": {"contact_manifest.json": {}}})
    artifacts = {
        "contact_manifest.json": {"surface_samples": "surfaces", "events": "events", "world": "Z-up", "floor": {},
                                  "visible_surfaces": {"thumb": {"body": "hand_r", "collision_geoms": ["collider"]}},
                                  "collision_geoms": {"collider": {"geom_id": 1}}},
        "surfaces": {"frames": [{"time_s": .04, "state_sha256": "hash", "surfaces": {"thumb": [-.001, [0, 0, -.001]]}}]},
        "events": {"chunks": ["chunk"]},
        "chunk": {"contacts": [{"sample": 0, "floor_contact": 1, "geom0": 0, "geom1": 1, "normal_force_N": 42.}]},
    }
    monkeypatch.setattr("human_models_mcp.contact_results.get_artifact", lambda _, name: {"data": json.dumps(artifacts[name])})
    result = get_contact("run", "hand_r", time_s=.04)
    assert result["measurement_status"] == "LOAD_BEARING"
    assert result["state_sha256"] == "hash" and result["surfaces"]["thumb"]["signed_distance_m"] == -.001
    assert get_contact("run", "hand_l", 0)["status"] == "invalid_input"

    # Bind the archived surface row to its exact serialized integration state.
    states = np.array([[.04, .2]])
    payload = BytesIO()
    np.savez_compressed(payload, states=states, time_s=np.array([.04]))
    bound = {"data": base64.b64encode(payload.getvalue()).decode()}
    artifacts["contact_manifest.json"]["states"] = "trajectory.npz"
    frame = artifacts["surfaces"]["frames"][0]
    frame["state_sha256"] = hashlib.sha256(states[0].tobytes()).hexdigest()
    monkeypatch.setattr("human_models_mcp.contact_results.get_artifact",
                        lambda _, name: bound if name == "trajectory.npz" else {"data": json.dumps(artifacts[name])})
    receipt = get_contact("run", "hand_r", 0)["scientific_quantity"]
    assert receipt["window"]["state_sha256"] == frame["state_sha256"]
    assert receipt["quantities"]["normal_force_N"]["native_identifier"] == "mj_contactForce[0]"
    assert receipt["uncertainty_interval"]["status"] == "NOT_AVAILABLE"
    frame["state_sha256"] = "wrong"
    assert get_contact("run", "hand_r", 0)["status"] == "integrity_error"
    frame["state_sha256"] = receipt["window"]["state_sha256"]
    bound["data"] = base64.b64encode(b"broken npz").decode()
    assert get_contact("run", "hand_r", 0)["status"] == "integrity_error"


def test_articulated_palms_partition_source_inertia_and_keep_native_ranges():
    from human_models_mcp.adapters.articulated_palms import FINGER_REST, name_joint, parallel_axis
    from human_models_mcp.adapters.hands import source_hand

    config = {"hand_support": "palms", "palm_technique": "chest_full"}
    mj, base, _ = pushup_model(**config)
    _, model, _ = pushup_model(**config, support_boundary="frictional_contact",
                               contact_profile="articulated_palms_v1")
    _, _, donor, _, _ = source_hand("palms")
    assert (model.nq, model.nu, model.neq) == (129, 700, 44)
    assert all(model.eq_type == mj.mjtEq.mjEQ_JOINT)
    np.testing.assert_array_equal(base.actuator_gainprm, model.actuator_gainprm)
    data = mj.MjData(model)
    legacy = mj.MjData(base)
    mj.mj_forward(model, data)
    mj.mj_forward(base, legacy)
    for side in "rl":
        name = "hand_" + side
        root = model.body(name).id
        b = base.body(name).id
        ids = [i for i in range(model.nbody) if model.body(i).name == name or model.body(i).name.startswith(name + "_")]
        np.testing.assert_allclose(model.body_mass[ids].sum(), base.body_mass[b], atol=1e-12)
        com = legacy.xipos[b]
        np.testing.assert_allclose(data.subtree_com[root], com, atol=1e-12)
        tensor = np.zeros((3, 3))
        for index in ids:
            r = data.ximat[index].reshape(3, 3)
            tensor += r @ np.diag(model.body_inertia[index]) @ r.T
            tensor += parallel_axis(model.body_mass[index], data.xipos[index] - com)
        r = legacy.ximat[b].reshape(3, 3)
        np.testing.assert_allclose(tensor, r @ np.diag(base.body_inertia[b]) @ r.T, atol=1e-12)
        for joint, target in FINGER_REST.items():
            j = model.joint(name_joint(side, joint)).id
            original = donor.joint(joint).id
            np.testing.assert_array_equal(model.jnt_range[j], donor.jnt_range[original])
            assert model.jnt_stiffness[j] == donor.jnt_stiffness[original]
            assert model.jnt_range[j, 0] <= target <= model.jnt_range[j, 1]
        moving = model.geom(f"palm_{side}_surface_hand_detail_{side}_4mc_new").id
        assert model.geom_bodyid[moving] != root
        assert model.geom_contype[moving] == FLOOR_BIT
