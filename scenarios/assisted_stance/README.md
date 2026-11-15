# assisted_stance

Integrate the pinned locomotion floor scene for 0.4 s with an explicit external world-frame pelvis PD force and torque. Native foot capsules supply part of the support; the measured external wrench supplies another part. All muscle excitations are zero and passive forces remain. Record support power/work, contact forces, COM/momentum dynamics and actual contact geometry. This is externally assisted model dynamics, not unassisted standing, biological control or balance validation.

```sh
python3 scripts/experiment.py --scenario assisted_stance
```

Physics is CPU MuJoCo 3.17.0. Renderer restores saved integration states.
The native source init has no floor contact; the initialization records its
world-z translation and sixteen knee coordinate changes. Collision geometry,
body masses and all source files remain unchanged. Contact margins can produce
forces at a positive geometric gap. Recorded gap and penetration are distinct.

For refinement use 400 steps at 0.001 s, preserving duration.
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
