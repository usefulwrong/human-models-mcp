# Controlled elbow engineering experiment

Run `run_scenario(scenario_id="elbow_tracking")` or
`python3 scripts/experiment.py --scenario elbow_tracking` after make build.

The full source model uses the same explicit compliant pelvis support as
loaded_elbow. A true sampled PD controller reads the current elbow angle and
velocity and applies a bounded generalized torque. Its reference is a synthetic
minimum-jerk ramp from 0 to 0.4 rad in 0.3 s, followed by a 0.1 s hold. It is not
a measured human trajectory. Gains are 40 N m/rad and 3 N m s/rad; saturation
is +/-8 N m. There is no external bias load. Muscles retain their source passive
dynamics; default excitations are all zero.

The CSV records actual angle, reference, tracking error, controller torque,
velocity, muscle state and support displacement with units. A torque at a saved
state applies to the following integration interval. Discrete applied work is
the sum of each held torque times its next angle increment, checked against
held torque times next-step velocity times dt. This is not full-system energy
conservation. GIF/plots restore the saved states, show the reference as a dashed
curve and retain actual physical time.

Supported duration is exactly 0.4 s: 200 steps at 2 ms or 400 at 1 ms. Reference
angle is bounded to 0.1–0.6 rad. Parameter changes are not guaranteed to track
accurately; error is reported. The fixture is artificial and compliant, with no
floor or whole-body posture policy. This is a controlled model experiment, not
a clinically validated functional task or muscle activation estimator.
