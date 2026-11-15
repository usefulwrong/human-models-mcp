# Models and provenance

The supported engine is MuJoCo **3.17.0** on CPU. Model files are from
[MuJoCo Menagerie at the pinned revision](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700),
`98a70c569c4c1b6da467a20012f766ee1f8dc521`. Every path, size and SHA-256 is in
[models.lock.json](../models.lock.json); `scripts/provision.py` downloads and
verifies them. Downloaded files are not modified by experiments.

| Variant | Source inventory | Use here |
| --- | --- | --- |
| Primary | 85 qpos / 85 qvel, 700 muscle actuators, 42 internal equalities | Sweeps, forward/loaded/tracking experiments, wrist benchmark and push-ups |
| Locomotion | 36 qpos / 36 qvel, 100 actuators, 16 equalities | Native contact probe and externally assisted stance |
| Manipulation | 48 qpos / 48 qvel, 81 actuators, 14 equalities | Source hand geometry, sites and wrapping routes for detailed-hand derivation; no grasp policy |

These are engine counts, not independent physiological degrees of freedom or
an anatomical census. Live discovery gives actual installed availability and
`get_joint_info` gives the compiled inventory. No second physics engine,
external anatomical atlas or trained policy is part of this preview.

The primary source has incomplete collision anatomy. Push-ups add declared
mechanical pads, floor and damping in memory. Detailed hands bake a source
manipulation posture into the primary rigid hands, reroute 48 extrinsic
transmissions and add vertically free sticking guides. The palm full profile
also changes two wrist bounds. Read the saved `model_recipe.json` and
[hand derivation](HAND_DETAIL.md), rather than treating the model ID alone as
an exact description of a derived run.

The upstream model directory declares Apache-2.0, retained in
[the model license](../notices/MS-Human-700-LICENSE). The upstream citation is
Zuo, He, Shao and Sui, *Self model for embodied intelligence: Modeling full-body
human musculoskeletal system and locomotion control with hierarchical
low-dimensional representation*, ICRA 2024, pp. 13062–13069. The pinned upstream
README is the authority for that attribution. Cite the model, Menagerie and
MuJoCo separately from this wrapper; see [CITATION.cff](../CITATION.cff).

No independent reconstruction of the historical origin of every upstream mesh
is claimed. The reviewed distribution's explicit license and notices are retained.
A model being available and licensed does not establish its scientific accuracy.
