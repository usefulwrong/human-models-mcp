# Prescribed elbow sweep

Call `run_scenario` with `scenario_id: elbow_sweep` and `{}` parameters after
discovery. The trusted `joint_sweep` backend loads the full upstream primary
model and calls `mj_forward` at nine independent joint coordinates (0.2–1.8 rad).
It reads musculotendon transmission length and its Jacobian. No time integration
or equilibrium solve occurs. `series.csv` is indexed by sample, not seconds.

Positive moment arm is defined as `-partial(length)/partial(angle)`; muscle
tension then contributes positive generalized torque. This is a partial
derivative with every other coordinate fixed, including coupled coordinates.
It is not a constrained anatomical moment arm or isolated muscle fiber length.

Numerical checks compare the Jacobian to a central difference and repeat exact
inputs. These checks do not establish experimental accuracy. The source model's
joint limits are model parameters, not population norms or safety limits.
