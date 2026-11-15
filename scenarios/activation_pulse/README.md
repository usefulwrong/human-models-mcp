# Short uncontrolled activation experiment

`run_scenario(scenario_id="activation_pulse", parameters={})` loads the unchanged
full primary MS-Human-700 model and calls `mj_step` ten times. At the model's
0.002 s timestep this integrates 0.020 s, with the source integrator and gravity.
The backend begins at upstream `init`, zeros qvel/activation/control, and sets
one constant excitation (default `BIClong_r: 0.3`). There is no supporting floor
or posture controller, and no equilibrium initialization. The whole body can
move as an uncontrolled initial-value system; this is not a biceps exercise.

CSV includes time in seconds, dimensionless excitation/activation, signed model
actuator force in newtons and musculotendon path length in metres. Negative
actuator force denotes pulling along this muscle transmission. Zero excitation
can still produce passive muscle force; never interpret it as zero total force.
All such force values are model outputs without experimental validation.

Parameters are limited to 1–25 steps and excitation [0, 1]. A run fails on any
engine warning, nonfinite state or out-of-range activation. Repeated full CSVs,
zero-excitation control and actual time/pose/frame identity are checked by real
MCP clients. Neither a finite trace nor a valid render establishes a person's
strength, joint loading, safety or accuracy of the source muscle parameters.
