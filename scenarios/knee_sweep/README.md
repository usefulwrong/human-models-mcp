# Prescribed knee sweep

Call `run_scenario` with `scenario_id: knee_sweep` and empty parameters.
The existing trusted `joint_sweep` backend evaluates the full primary
MS-Human-700 model at nine `knee_angle_r` coordinates from 0.2 to 1.0 rad.
It measures the `recfem_r` musculotendon transmission path length and
`-partial L/partial q` using MuJoCo's Jacobian and independent finite differences.

For these defaults, path length increases and the signed moment arm is negative.
This complements the default elbow experiment's opposite signs. Those signs
are invariants of these two pinned configurations, not universal human ranges
or an independent validation of either anatomical model.

All other generalized coordinates stay at upstream `init`. In particular, the
additional tibial and patellar coordinates prescribed by the source model's
knee equality polynomials are **not** updated. There is no equality projection,
equilibrium solve, physiological knee trajectory, force estimate or time integration.
The CSV axis is sample index, not seconds. Do not interpret the PNG as an
anatomically constrained knee pose or infer knee loading from the path length.

The selected range stays within the hinge's source range [0, 2.4] rad with room
for the ±1e-6 rad probes. Numerical consistency and repeated runs are tested
through both real MCP transports. Scientific evidence level: numerical sanity.
