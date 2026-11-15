# Locally equality-consistent knee path

The selected knee angle drives eight tibial/patellar coordinates by the source
quartic equations, using the engine's qpos0 references. `mj_forward` checks the
actual equality residuals. An independent linear solve of the engine constraint
Jacobian checks the path tangent; central differences of path length check its
effective signed moment arm `-dL/dq`. No motion is integrated.

Defaults use 0.2–0.6 rad. The source's coupled rotation polynomial overshoots
its declared joint range within part of 0.2–1.0 rad, even though the primary
knee coordinate itself is inside its range. The new method checks polynomial
extrema across the entire requested interval and rejects this conflict rather
than clipping or silently relaxing limits.

Compare against `knee_sweep` with `end_rad: 0.6` at the same angles. That older experiment keeps
the coupled coordinates fixed and measures a different partial derivative.
Only these eight local equality constraints are claimed consistent. Other
equalities, physiological accuracy, global equilibrium and collision-free
admissibility are not established. The source's soft equality constraints in a
dynamic simulation need not have exactly zero residuals; this path prescribes
the polynomial manifold rather than reproducing a dynamic trial.
