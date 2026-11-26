---
name: human-models-mcp
description: Use the local human-models-mcp server to discover musculoskeletal model capabilities, run supported experiments, and retrieve measured artifacts with provenance.
---

# Model-to-evidence workflow

Use the connected server's tools; do not replace unavailable model outputs with
estimates from language-model knowledge. Tool prefixes may be supplied by the
host, but these are the server's exact tool names.

1. Call `list_models`, then `describe_model(model_id="ms_human_700")` and
   `get_model_capabilities(model_id="ms_human_700")`. Check availability and
   limitations before choosing a computation. Use `get_joint_info` for actual
   engine joint ranges and actuator names; these are model identifiers, not a
   universal anatomy terminology system.
   `search_sources(query="BIClong_r")` finds the pinned source identifier,
   manual and scenario descriptions with revision/hash/license. Search excerpts
   are references, not engine measurements or a universal anatomy atlas.
2. Call `list_scenarios` and `describe_scenario(scenario_id="elbow_sweep")`.
   Respect the recorded `static_pose` method and parameter units/ranges.
   `knee_sweep` is another prescribed-coordinate experiment. For real time
   integration use `activation_pulse`, whose method is `dynamic_forward` and
   scope is a short uncontrolled initial-value model, not an exercise controller.
   `knee_coupled` instead follows eight source equality polynomials over a checked
   interval; it is still `static_pose`. `loaded_elbow` integrates the full model
   with a documented soft pelvis fixture, muscle excitation and elbow torque.
   Its saved-state frames, GIF and plots describe a loaded initial-value experiment.
3. Call `run_scenario(scenario_id="elbow_sweep", parameters={})`. Use an optional
   unique `idempotency_key` only for retrying the same request. Omit it for a
   separate reproducibility trial. A `busy` response can be retried later;
   `invalid_input` needs correction; `unsupported` has no numerical answer.
4. Read `get_result(run_id=...)`. Require `status="computed"`, exact engine and
   model revision/hash, units, method and scientific limitations. Requested render
   failure makes the overall run `failed`; `execution.numeric_status="computed"`
   can retain numeric work, but does not turn that run into success. An interrupted
   run is `failed`, never a usable completed trajectory.
   Inspect `scientific.checks` and retrieve `validation.json`; its hash must match
   `scientific.validation_contract_sha256`. Numerical sanity is not external validation.
5. Fetch `get_artifact(run_id=..., artifact_id="series.csv")` and
   `get_artifact(..., artifact_id="summary.json")`. Artifact IDs come from the
   manifest. Decode PNG base64 if present, verify SHA-256, and read `frame.json`
   and `poses.json` before describing the picture as a calculated pose.
   For `loaded_elbow`, fetch `animation.gif`, `frames.json`, `trajectory.npz`
   and `plots.png`; verify state/archive/frame hashes and read the fixture recipe
   in `model.derivation`. Physics remains CPU even with `nvidia_egl` graphics.

For an independently executable reference client, use `make client` or the
[public SDK client](../../examples/mcp-client/client.py). It imports no server
Python API. See [interpretation rules](../scientific-interpretation/SKILL.md)
when drawing conclusions. Do not label the elbow sweep as dynamics, muscle-force
estimation, a person's joint limits or evidence of movement safety.

## v0.4 discovery and evidence

Read the selected scenario's defaults as well as its method and scope. Schema
property defaults reflect that folder's effective defaults, including authored
scenarios; do not substitute another sweep's example values. Omit parameters
you do not intend to override. This rule addresses an observed real-agent issue
where shared backend defaults could prepopulate the wrong joint/range.

`describe_scenario.parameter_schema` contains the actual accepted parameter
bounds and literal choices. Read it before changing defaults. The model card's
`unsupported` list supplies canonical quantity names; a quantity query returns
`reason=known_unsupported` or `unknown_quantity`, both without numeric estimates.
`model.integrity=sha256_verified_for_execution` in a run describes execution
verification; the lightweight catalog's `not_verified` does not record a run.

`elbow_tracking` is real feedback dynamics using an external joint PD servo,
synthetic engineering reference and the stated soft fixture. It is not
muscle-driven neural control, observed motion replay, gait or exercise.
`wrist_benchmark` compares ten neutral-wrist moment arms against published
cadaver means. Read `comparison.json`, `reference_metadata.json`,
`experimental_reference.csv` and `reference_article.xml`. Experimental mean
comparison does not make the whole model experimentally or clinically validated;
other scenarios do not inherit it. Query `search_sources(query="Nichols")` for
that attributed source; wrapper scope documents have a distinct evidence type.

For a named standalone result, `make experiment` prints the local `index.html`
path and downloads all verified files. Select another supported scenario with
`python3 scripts/experiment.py --scenario wrist_benchmark`. No internal UUID
search or container filesystem access is needed. The server still returns UUIDs
for protocol calls and never accepts arbitrary host output paths.

## Body contact experiments (0.5)

Read the selected scenario.model, then describe that model. The primary
700-actuator card serves the seven original scenarios; ms_human_700_locomotion
has 36 coordinates, 100 lower-body actuators and the upstream floor. Selecting
the first catalog entry for every scenario is incorrect.

For contact discovery use contact_probe, ground_reaction_forces, center_of_mass
and support_polygon capabilities. standing_contact_probe is a 0.2 s passive
transient; assisted_stance is 0.4 s with a recorded external pelvis PD wrench.
Neither enables standing_balance. Inspect model_recipe.json,
initial_conditions.json, contact_map.json, series.csv and contacts.json; the
latter lists flat artifact IDs for contact chunks. Fetch those IDs via
get_artifact. Contact traces use force/COM columns, not length_m/activation.

Use the run's units and named checks. computed is execution status;
scientific.numerical_status=validated_for_named_checks is limited to the listed
computational conditions, with validation_level still numerical_sanity.
unsupported and failed provide no successful replacement result; partial files
from a failed run remain unvalidated. Rendering requested by a scenario is part
of its execution success. If render=false, frames/GIF are not expected.

make experiment now chooses the contact probe and prints a new local index.html.
For reruns choose a new output directory or omit --output; existing directories
are never overwritten. Direct MCP calls still use the returned UUID.

## Saved-state visualization (0.6)

Four additive tools are available: list_render_profiles, render_result,
get_render_job and get_render_artifact. Read the
[visualization workflow](../scientific-visualization/SKILL.md) before using them.
Use an existing computed trajectory; rendering does not rerun physics. Download
large video/scene files with bounded chunks, not the original two MiB tool.

## Full primary-model push-up (0.7)

Discover the `pushup` folder and read its schema. Default `control: muscle`
uses all 700 native muscle actuators with bounded excitation, real activation
dynamics, added mechanical palm/toe pads and declared passive damping. No root
actuator, pelvis fixture or external body wrench supports the cycle. The separate
`control: external` experiment uses generalized joint torques and must be labeled
external control. Do not infer a muscle-driven result from that mode.

Require `computed`, then inspect each `scientific.acceptance` gate, not just
execution status. Fetch `summary.json`, `series.csv`, `actuators.json`,
`trajectory_metadata.json`, `muscle_ranking.json` and every listed `muscles_*.npz`.
The latter contain 700-column excitation, activation, signed force, path length,
velocity, power and sparse transmission contributions in declared source order.
Rank using a declared computed measure, not invented EMG. The default ranking
uses absolute force impulse and includes passive forces. Groups with uncertain
names remain unmapped. Retrieve contacts and saved states via manifest IDs.

Use `render_result` with bones, muscle_paths, contact_forces, center_of_mass and
joint_axes. Source archives retain all measured muscles, while visible paths are
a declared subset. Require PNG, MP4, GIF, .blend, source.zip and passport.json;
verify hashes, inspect start/bottom/end frames and report scientific limits.
The model does not provide flat-palm pressure, independent scapula control,
registered muscle volumes, calibrated human activation or safety predictions.

The current preview uses `pushup_flat_palm`. Query its exact sample with
`get_contact`, inspect `distributed_palms_and_digits` independently from
`full_pushup`, and retain the actual science statuses in every replay.
[Contact model and limits](../../docs/CONTACT_MODEL_AND_LIMITATIONS.md)

`pushup_palms` and `pushup_knuckles` add fixed source-derived hand postures,
48 rerouted extrinsic hand/wrist transmissions and multi-point support. Their
default `assisted_muscle` mode records real muscle activation/forces plus explicit
external residual joint assistance; it cannot inherit the original unassisted
scenario's muscle-driven PASS. Read `hand_support_geometry` as well as the other
gates. Retrieve `wrists.json` and the native wrist angle/torque and floor-wrench
columns in `series.csv`. Passive/constraint generalized torques are not ligament
tension. Discrete wrist ligaments and independent finger dynamics are absent.
Use regional visual layers and `camera_view: hands` as described in the
[hand-detail notes](../../docs/HAND_DETAIL.md).

The historical `pushup_palms` 1.5 defaults to `palm_technique: chest_full`: 33 frozen
synthetic targets, roughly shoulder-width supports and a separately declared
wrist envelope. Require `elbow_extension` and `wrist_extension_envelope` PASS;
read `wrist_range_derivation` and `palm_reference_input.json`. Only two extension
coordinate bounds differ from the pinned source; this is literature-informed
engineering, not subject calibration or an unmodified-native-range result.
`chest_level` retains the former native-range wide partial trajectory, and
`legacy_reach` retains the rejected reach. Do not merge their scientific statuses.

For legacy fixed-point runs inspect `stationary_supports` and retrieve
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
[reference-first rule](../../docs/MOVEMENT_METHODS.md).
Search for real people performing the named variant, open the actual images or
video frames, and record viewed phases/angles and source URLs before choosing
the trajectory. Compare model limits with those references; preserve an honest
negative result if they are incompatible. A numeric PASS is not a technique PASS.
For push-ups explicitly inspect bilateral pectoral forces/activation; rendering
colors must remain computed values and cannot be supplied from expected EMG.

## Evidence and recipes

Discover capabilities and scenario scope before execution. Inspect named gates,
then use a listed render recipe and request Evidence Contract entries with
`get_result(run_id, claim_id=...)`. The reference importer is a separate local
workflow for licensed data. Use the report's named quantities and evidence
class when drawing conclusions.

[Anatomical evidence guide](../../docs/ANATOMICAL_EVIDENCE.md)

## One calculation with several views

For a supported push-up, call `run_scenario` with optional
`visualization: {recipes: [...], options: {...}}` after discovery. Keep the
run UUID and each job UUID. Examine `computed_status`, `acceptance`,
`human_validation_status` and `human_safety_status` before interpreting it.
A partial response includes per-recipe errors. An identical study key can
reuse the calculation; use a new key for an independent repetition.
