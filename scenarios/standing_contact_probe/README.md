# standing_contact_probe

Integrate the pinned locomotion model and upstream floor for 0.2 s with zero muscle excitations. Enforce sixteen local source knee equalities, then align the lowest native foot capsule to 0.2 mm geometric clearance. Measure world ground reaction, COM and angular-momentum balance, point-contact support hull, conditional ground-wrench CoP and joint-limit residuals. This is a passive contact transient, not initialized at equilibrium or validated human standing.

```sh
python3 scripts/experiment.py --scenario standing_contact_probe
```

Physics is CPU MuJoCo 3.17.0. Renderer restores saved integration states.
The native source init has no floor contact; the initialization records its
world-z translation and sixteen knee coordinate changes. Collision geometry,
body masses and all source files remain unchanged. Contact margins can produce
forces at a positive geometric gap. Recorded gap and penetration are distinct.

For refinement use 200 steps at 0.001 s, preserving duration.
A small initial world-x velocity is a stated perturbation, not motion capture.
Root-height offsets causing initial penetration or missing bilateral foot contacts
are invalid_input. Invalid controller names/gains and loads above 100 N are rejected.
Read model_recipe.json and initial_conditions.json before interpreting results.

GRF plus gravity and any declared external load/support equals M*a_COM; ground
and external moments about COM equal Hdot_COM. Kinematic matrix time derivatives
use central differences at 1 microsecond. Soft-limit tolerances (0.001 rad,
0.0001 m), maximum penetration (0.005 m), and force/moment tolerances (1e-5 N/N m)
are engineering guards, not human accuracy limits. They can reject allowed input
combinations. No unsupported result is replaced by a plausible number.

The point-contact support hull and ground-wrench CoP are geometric/wrench
summaries; their inclusion tests do not certify balance. External pelvis support,
if enabled, has its measured force, torque, power and work recorded explicitly.
No standing_balance or neuromuscular-control capability is enabled by this folder.
