---
name: scientific-interpretation
description: Interpret human-models-mcp measurements by checking units, provenance, computation method and evidence limits before making biomechanical claims.
---

# Interpret the result that was actually computed

Read `get_result` and its `scientific` and `execution` fields, then use
`get_artifact` to inspect the numeric table. Cite run UUID, model revision/hash,
engine version, scenario parameters and the source citations included in that
run. Separate the engine observation from any outside hypothesis.

For `elbow_sweep`, the independent variable is prescribed hinge angle in rad;
the CSV index is a sample, not time. `length_m` is a musculotendon transmission
path in metres, not an isolated muscle fiber length. `moment_arm_m` is
`-partial L/partial q`, with every other coordinate fixed, including coupled
coordinates. No equilibrium or physiological constraint path is solved.

`knee_sweep` has the same partial-coordinate meaning. `knee_coupled` instead
changes eight tibial/patellar coordinates according to source equality polynomials.
Its effective arm is `-dL/dq` along that path. Check translation residuals (m),
rotation residuals (rad) and implicit-tangent checks in their separate units.
Other equalities, collision validity, equilibrium and human knee accuracy are
not established. A rejected range must not be fixed by clipping dependent coordinates.

For `activation_pulse`, the independent variable is actual integrated time in
seconds. `execution.integration_steps` counts real `mj_step` calls. The model
starts at upstream init with zero velocity/activation and one constant excitation;
it has no floor or posture controller. Excitation and activation are dimensionless
and distinct. `actuator_force_N` is signed model transmission force in newtons,
not a validated biological measurement or joint reaction. Zero excitation can
still produce passive force. State the initial conditions, integration duration
and lack of experimental force comparison whenever interpreting this experiment.

`loaded_elbow` adds a soft pelvis-to-world fixture at the initial pelvis origin
and a prescribed elbow torque (N m). Record this model derivation, excitation,
time step, initial conditions and measured fixture displacement. Applied work
is torque times angle change (J); the sampled-power comparison is a numerical
quadrature check, not conservation of the whole model's mechanical energy.
The zero-torque control still has muscle excitation, passive forces and gravity.
A step-refinement difference is a sensitivity observation, not an uncertainty
interval against real humans. No posture controller or calibrated exercise is present.

`search_sources` returns attributed manual excerpts, source model identifiers
and wrapper scenario descriptions. Their SHA-256/version/license identify the
source; a search match does not validate a measurement or an anatomical claim.

A passed central-difference check and repeat-run comparison support
`numerical_sanity`. They do not establish a percentage accuracy against humans,
experimental validation, a confidence interval, normative range or injury risk.
Report only the precision useful for the question; do not imply extra biological
certainty from many stored decimal places.

`computed` is an execution status, `unvalidated` is an evidence level,
`unsupported` means no available scientific operation, and `failed` means the
requested operation did not finish its contract. Never turn one into another.

Use `get_model_capabilities(model_id="ms_human_700", quantity="medical_safety")`
for safety/clinical questions: it returns `unsupported`. The same boundary
applies to disc pressure, spinal cord, internal organs, breathing, diagnosis,
age/sex/pathology customization and personal exercise clearance. Do not infer
these from joint geometry. Use appropriate primary evidence separately if the
user needs a claim about real people, and explain the gap to this model.

An engine PNG is a visualization of its recorded state. Check `frame.json`
against `poses.json` and the run's model. Rendering on NVIDIA EGL does not mean
the physics/model calculation ran on GPU. Further scope details are in
[SCIENTIFIC_SCOPE.md](../../docs/SCIENTIFIC_SCOPE.md).
For motion check `frames.json`: each frame identifies a saved integration state,
physical time, camera and hashes. GIF playback is deliberately slowed; the raw
state times, not GIF playback duration, define the simulated experiment.

## External reference and feedback control

For `wrist_benchmark`, use only the nonimpaired means and specimen SD from
Nichols et al. 2016 Table 2. Units are cm in the publication and m in the CSV;
positive directions are extension and ulnar deviation. Model neutral is defined
from radius/third-metacarpal mesh PCA axes, with radial direction from fifth to
second metacarpal centroids. Two source carpal couplings and a physical-angle
Jacobian are included. Source joint names and their raw partial moment arms
cannot be substituted for these functional derivatives.

This is an external published-data comparison under explicit coordinate/posture
assumptions. The benchmark fits no experimental values, but upstream calibration
overlap is unknown, so do not call it a proven held-out validation dataset.
Between-specimen SD is not a confidence interval, accuracy tolerance, prediction
uncertainty or evidence for sex-specific models. An RMSE against five muscles
at one neutral pose cannot validate dynamic force, other joints or clinical use.
The run's numerical_sanity grade and its scoped experimental comparison are
separate fields; cite both accurately.

`elbow_tracking` closes a real sampled feedback loop with torque saturation.
Its target is a synthetic minimum-jerk engineering trajectory. Read
`execution.controller`, tracking error and torque units. The torque at one saved
state drives the next interval. Small tracking error tests this simulated
servo/fixture setup, not human motor control or muscle recruitment.

Check each hash's declared encoding. `qpos_sha256` uses the returned
`qpos_hash_encoding` (UTF-8 default json.dumps), not an assumed float64 buffer.
Frame state hashes use `state_hash_encoding` and the saved NPZ dtype/order.
Whole-file artifact SHA-256 always hashes the transferred raw bytes. Do not
interpret a guessed serialization mismatch as a scientific-model failure.

## Contact and external support

Check the run's model variant, world axes, floor/masks/exclusions and solver
settings before interpreting a ground reaction. Source names do not guarantee
world orientation: the compiled locomotion pelvis_ty axis is world vertical.
Initialization aligns native foot capsules after enforcing sixteen knee
couplings; it is a modified initial state, not measured posture or equilibrium.

mj_contactForce gives local force/torque on contact.geom[1] (the second geom). Contact frame axes are rows;
world wrench = frame.T @ local. Reverse sign for the body when contact.geom[1] is the
floor. Geometric gap, contact inclusion margin, penetration and load-bearing
normal force are separate quantities. Native positive margins allow force at a
positive geometric gap. Visual bone meshes mostly do not collide; capsules do
not model complete skin, tissue clearance or plantar pressure.

Use M*a_COM = GRF + M*g + declared external force. assisted_stance adds a
bounded world-frame pelvis force/torque, with measured power/work; account for
it before comparing GRF with weight. A transient does not require GRF=mg. Ground
and external moments about COM are checked against Hdot_COM. Newton consistency,
state restart and smaller-step agreement are numerical evidence, not measured
human accuracy or biological control validation.

The support hull uses current force-bearing point contacts, not anatomical sole
area. CoP is an equivalent net ground-wrench point on z=0 only when Fz>1e-6 N;
it is not a ZMP measurement. COM/CoP inclusion does not prove dynamic balance,
complete contact validity, robust standing or safety. External support must
appear in the explanation. standing_balance, running, organs and sex-specific
customization remain unsupported. The wrist reference comparison belongs to a
different model/task and does not validate contact or the support controller.

## Blender media (0.6)

A completed render is a saved-state geometric replay. Read passport.json and
frames.json before describing it: physical time differs from playback time.
Native vertex/transform checks establish transfer consistency only. Muscle tubes
are display paths, not tissue volumes; HRA identifiers do not establish atlas
registration. Materials/lighting change appearance, not physics. Applied moment
arrows are axial pseudovectors, not joint reaction measurements. Original physics
status and separate render-job status must both be described accurately. See
[scientific-visualization](../scientific-visualization/SKILL.md).

## Push-up research (0.7)

Distinguish `full_cycle_kinematics`, `four_supports`, `numerical_bounds`,
`muscle_driven`, human validation and anatomical registration. A computed negative
experiment can fail exercise gates. In default muscle mode every external
qfrc_applied/xfrc_applied is zero; native excitation and activation generate the
active forces. Added passive damping, contact proxies and source joint equalities
are part of the experiment and must be disclosed. External mode cannot inherit a
muscle-driven PASS. Inspect measured support displacement, reaction forces and
constraint violations even when the full-cycle gate passes.

Sparse rows are dL/dq, not minus dL/dq: actuator contribution equals row times
signed MuJoCo force. Tensile force is generally negative. Power equals signed
force times transmission velocity. Absolute force impulse includes passive
force and is not a causal importance or EMG ranking. Group averages are averages
of source paths, not muscle volume weighting or observed EMG. EMG comparisons
are qualitative literature context; no percent-MVIC conversion is available.

For `pushup_palms` and `pushup_knuckles`, defaults use `assisted_muscle`: actual
muscles plus external residual generalized joint forces, with zero root/body
assistance. `full_pushup=PASS` does not imply `muscle_driven=PASS`. Inspect the
additional `hand_support_geometry` gate and `wrists.json`. Floor moments about
the wrist are external wrench components, not internal joint reactions; native
passive/constraint torques are not ligament tensions. Finger poses are fixed
source-derived configurations. Wrist coordinates are native model angles, not
calibrated clinical extension. Different reference hand placement prevents an
isolated palm-versus-knuckle causal load comparison. Discrete ligaments, intrinsic
finger control and separate tendon elasticity are not modeled. See
[hand-detail derivation](../../docs/HAND_DETAIL.md).

For detailed-hand runs require `stationary_supports=PASS` and retrieve
`support_stationarity.json`: all native hand/toe pads and four prescribed points
must stay within 0.5 mm horizontally at every integration step. Defaults are
`support_boundary: fixed_points`, 0.5 ms integration and 4.4 s total. Horizontal
guides prescribe ideal sticking while vertical native contact stays unilateral;
check combined guide/native friction reactions, not position alone. Do not infer
stationarity for historical renders. See `docs/HAND_DETAIL.md`.

For current knuckle runs also require `neutral_knuckle_grip`, `tucked_elbows`
and `bottom_depth` PASS. Read the grip-axis cosines, elbow flare and shoulder
height above the elbow in `series.csv`/`summary.json`. The earlier backward,
flared grip is rejected even when its immutable old cycle/contact gates passed;
see `tests/fixtures/rejected_knuckle_pose.json`. Native joint ranges must not be
widened to force a reference. Muscle forces require recomputation after changing
technique; neither expected EMG nor rendering colors may manufacture them.

Before implementing or accepting human exercise motion, follow the repository
[reference-first rule](../../AGENTS.md#human-movement-references-before-implementation).
Search for real people performing the named variant, open the actual images or
video frames, and record viewed phases/angles and source URLs before choosing
the trajectory. Compare model limits with those references; preserve an honest
negative result if they are incompatible. A numeric PASS is not a technique PASS.
For push-ups explicitly inspect bilateral pectoral forces/activation; rendering
colors must remain computed values and cannot be supplied from expected EMG.

## Evidence and recipes in v0.8

Use `get_result(run_id, claim_id="metric:<name>")` and render `evidence.json`.
Check execution, named thresholds, mapping, and external comparison separately.
Only claim the named observable. Treat absent comparisons as unavailable, model
activation as dimensionless, and skinning as a visual rig. A render or simulation
PASS gives no evidence of human safety, tissue mechanics or EMG.

[Anatomical evidence guide](../../docs/V08_ANATOMICAL_EVIDENCE.md)

## Claim-specific statuses

Read the full `acceptance` map and the individually named `numeric_checks`.
Use `get_result(run_id, claim_id="gate:muscle_driven")` for muscle-only control.
A run can be completed with `full_pushup: FAIL`, or it can pass the exercise
gates with `muscle_driven: NOT_ACHIEVED`. Treat use of residual assistance
and prescribed sticking points as interpretation limits. Read
`reference_comparison`, `human_validation_status` and `human_safety_status`
before writing claims about people. Never infer a confidence percentage.
