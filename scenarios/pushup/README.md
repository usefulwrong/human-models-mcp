# Full-body push-up research scenario

Run `run_scenario("pushup", {"control": "muscle", "render": false})` through MCP,
or `human_models_mcp.core.run_scenario("pushup", {"render": False})` in Python.
The default muscle controller excites all available native muscle actuators;
activation evolves through MuJoCo muscle dynamics. `control: external` selects
an explicitly external joint servo and leaves muscle excitations zero.
No pelvis fixture, root actuator, body wrench or pose reset supports the motion.

Inspect `scientific.acceptance`, `summary.json`, `series.csv`, `actuators.json`,
`muscle_ranking.json` and `muscles_*.npz`. `trajectory_metadata.json` defines array
orders, force signs and sparse actuator contributions. States are saved every
20 ms, control updates every 10 ms, integration uses 1 ms or 0.5 ms. All engine
steps are checked for finite state, activation bounds, contacts and joint limits.
Use `render_result` separately for Blender saved-state replay.

The reference has a 0.2 s settling interval, a 2 s descent/ascent cycle and a
0.2 s final hold. Four-support fraction excludes the initial settling interval.
The model uses declared spherical contact pads, extra viscous damping and source
scapulohumeral equalities. It does not represent independently controlled scapulae,
flat-palm contact pressure, complete body-floor collision, or human validation.
A run may be computed while exercise/contact/numerical gates fail. Such a run
is retained as a negative experiment, never advertised as a successful exercise.
