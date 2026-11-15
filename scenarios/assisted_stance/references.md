# Sources and limits

- Pinned source model and floor, Apache-2.0: https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700
- MuJoCo 3.17.0 contact frames and force decoding: https://mujoco.readthedocs.io/en/3.17.0/programming/simulation.html#contacts
- Force API: https://mujoco.readthedocs.io/en/3.17.0/APIreference/APIfunctions.html#mj-contactforce
- Actual force-on-geom1 sign and transposed frame: https://github.com/google-deepmind/mujoco/blob/3.17.0/src/engine/engine_core_smooth.c
- Soft contact/constraint formulation: https://mujoco.readthedocs.io/en/3.17.0/computation/index.html
- Research release reviewed at 8eac35bb8788a183c9e8698ee1207c1bbe654094: https://huggingface.co/BAAI/MS-Human-700/tree/8eac35bb8788a183c9e8698ee1207c1bbe654094

Accessed 2026-11-06. No reference motion or trained policy is executed here.
The BAAI release explicitly excludes trained checkpoints/evaluation results.
Published wrist cadaver means do not validate locomotion contact or support.
