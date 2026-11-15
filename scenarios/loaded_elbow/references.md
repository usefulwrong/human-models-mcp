# Sources and scope

- [Pinned MS-Human-700](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700), Apache-2.0, accessed 2026-11-06.
- [MuJoCo 3.17.0 weld equality](https://mujoco.readthedocs.io/en/3.17.0/XMLreference.html#equality-weld): the added fixture is a soft constraint, not exact fixation.
- [MuJoCo computation](https://mujoco.readthedocs.io/en/3.17.0/computation/index.html): generalized forces, Euler integration, muscle actuator transmission and activation dynamics.
- [MuJoCo state](https://mujoco.readthedocs.io/en/3.17.0/APIreference/APItypes.html#mjtstate): integration-state serialization.

The source model is unmodified on disk. The added weld and time-step override are
recorded in each manifest, with the SHA256 of the derived XML. Model force outputs
are not independently validated biological forces or physiological predictions.
Muscle path geometry is not a volumetric muscle atlas. No floor or new collision
coverage is added; frames do not certify physical admissibility or movement safety.
