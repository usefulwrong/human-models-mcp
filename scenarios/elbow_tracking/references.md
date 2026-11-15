# Sources and engineering assumptions

- [Pinned MS-Human-700](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700), Apache-2.0, accessed 2026-11-06.
- [MuJoCo 3.17.0 computation](https://mujoco.readthedocs.io/en/3.17.0/computation/index.html), generalized applied forces and Euler integration.
- Reference formula is an explicitly constructed engineering input: target*(10u^3-15u^4+6u^5), u=min(t/0.3,1). Its analytic derivative supplies reference velocity. It is not sourced human motion data.
- External controller: clip(40*(q_ref-q)+3*(v_ref-v), -8, 8) N m. Gains were selected in an engine stability probe, not fitted to human observations.

The physical model is unchanged except the recorded compliant pelvis fixture.
The servo is a prescribed external actuator, not muscle-driven neural control.
No gait, balance, contact task, physiological controller or patient-specific
movement is asserted. A separate cadaver wrist comparison supplies no validation
for this controller. Numerical tracking checks are not experimental validation.
