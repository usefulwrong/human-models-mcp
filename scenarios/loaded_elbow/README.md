# Loaded elbow initial-value experiment

Run `run_scenario(scenario_id="loaded_elbow")` via MCP. Default duration is 0.2 s.
This uses the whole pinned musculoskeletal model with an explicitly derived soft
pelvis fixture, not an isolated hinge. The fixture is compliant; its displacement
is measured. Constant 2 N m generalized elbow torque and 0.15 BIClong_r excitation
are experimental inputs, not measured muscle activity. All other excitations are
zero. The initial state is the source init keyframe with zero velocity/activation,
not an equilibrium. Other coordinates evolve under gravity and source constraints.

`series.csv` records angles (rad), velocities (rad/s), transmission force (N),
activation (1), path length (m), support displacement (m) and torque (N m).
Applied work is torque times angle change (J); an independent sampled-power
integral is checked with the Euler endpoint quadrature bound. The derived MJCF,
full integration-state archive and recorded overrides preserve the derivation.
Frames restore saved states without integrating. GIF playback is slowed 10 times.

This is numerical model behavior, without experimental or clinical validation.
Changing time step requires changing steps to keep the same physical duration.
