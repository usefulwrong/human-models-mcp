---
name: scenario-authoring
description: Add declarative human-models-mcp experiment folders using the existing trusted backend, pinned model and measurable numerical checks.
---

# Add a folder, then prove it runs

Copy `scenarios/elbow_sweep/` to a new lowercase underscore ID and set the YAML
`id` to the folder name. Update title, scope, defaults, README, references and
validation instructions to describe the actual experiment. Preserve exact
engine/model versions and use `backend: joint_sweep`, `method: static_pose` and
the existing required capabilities. The schema is
[registry.py](../../src/human_models_mcp/registry.py).
For a forward experiment, copy `scenarios/activation_pulse/` instead and preserve
`backend: activation_forward`, `method: dynamic_forward`. Only muscle ID,
dimensionless excitation [0, 1], steps 1–25 and rendering are configurable;
there is no arbitrary controller, model path, Python or shell parameter.
For the supported fixture/load experiment copy `scenarios/loaded_elbow/` and
retain backend/method. Its bounded schema permits BIClong_r and elbow_flexion_r,
excitation 0–0.5, torque -5–5 N m, 25–200 steps, and step size 0.001 or 0.002 s.
For a coupled knee study copy `scenarios/knee_coupled/`; the backend requires a
source knee root and its eight active equalities, validates polynomial extrema
against dependent joint limits, and checks the local constraint Jacobian.
The default checked interval is 0.2–0.6 rad; 0.2–1.0 rad is rejected because a
source dependent coordinate exceeds its own bound inside that interval.

Choose a real hinge joint and tendon-transmission muscle actuator using
`get_joint_info(model_id="ms_human_700")`. Angles and ±1e-6 rad probes must stay
inside model limits; samples must be an integer from 3 through 101. A manifest
cannot introduce Python, shell, a new model/solver, assets from an arbitrary
path, or a scientific method that the backend does not implement.

`list_scenarios` discovers the folder without core edits and quarantines invalid
folders with diagnostics. For an existing image, rebuild after adding the
folder; `make build` includes it. Then use `describe_scenario`, `run_scenario`,
`get_result` and `get_artifact` from a fresh client. Do not call a manifest
executable merely because its schema passes: require a real engine run and
finite-difference checks for the selected configuration. Nonsmooth wrapping
branches can fail those checks and require a different stated experiment.
`validation.yaml` is schema-checked and its checks are executed by the trusted
backend. Changing its conditions changes the hashed scenario contract.
Static default sign checks apply to the declared default joint/muscle/range;
they are not universal expectations for parameter overrides. Forward checks
require finite state, no engine warnings and activation bounds. The maximum
repeat tolerance is 1e-12 for sweep metrics and 1e-10 for forward metrics, in
each recorded metric's unit; actual repeat comparisons are part of E2E.

Run `make test` and `make e2e`. The E2E itself creates a temporary valid folder
and a broken folder and verifies discovery/quarantine through MCP. A genuinely
new backend needs reviewed Python implementation and a new real-engine E2E;
YAML is not an executable extension mechanism.

## Additional trusted backends

For a bounded feedback experiment copy `scenarios/elbow_tracking/`: preserve
backend `elbow_tracking`, controller `joint_pd` and dynamic_forward. Read the live
parameter_schema: 0.4 s duration requires 200 steps at 2 ms or 400 steps at 1 ms;
reference angle is 0.1–0.6 rad. Gains/torque saturation are trusted code, not
arbitrary YAML expressions. Do not describe this external servo as a human
muscle controller or experimental motion capture.

`scenarios/wrist_benchmark/` uses a fixed reviewed dataset and physical-coordinate
method. Its reference_id and ten observations are fixed. A new experimental
dataset or coordinate mapping requires source/license/comparability review and
backend tests; changing YAML prose cannot register evidence or promote a grade.

For an isolated agent authoring check, copy an existing scenario into a new
folder under a temporary project-local scenarios directory, set its id to the
folder name and preserve the required files. The public SDK bridge
`examples/mcp-client/call_tool.py` supports `--scenario-dir PATH` as a trusted
local test mount. This CLI path is not an MCP parameter. Discover the new folder,
run it and verify the CSV/validation artifact. A malformed folder must appear in
quarantined without preventing discovery/execution of the valid one. Production
installation remains a folder addition followed by make build.

## Contact folders

Copy standing_contact_probe or assisted_stance to reuse a trusted contact
backend, preserving model=ms_human_700_locomotion, engine/model revisions and
method=dynamic_forward. Keep the appropriate backend and assistance literal.
The probe lasts 0.2 s (100 steps at 2 ms or 200 at 1 ms); assistance lasts 0.4 s
(200 or 400). Read the live schema for load, velocity and gain bounds.

A folder cannot introduce collision shapes, a new floor/model, a weld, a Python
controller or a reference trajectory. Those require reviewed backend/model
changes and new provenance. The backend records native collision settings,
initial root alignment and knee equalities, force/moment/friction checks and
separate rad/m soft-limit guards. validation.yaml bounds are engineering tests,
not tolerances of human anatomy. Stronger checks can fail and retain partial
numeric files; do not relabel them computed. Bad initial penetration or missing
bilateral foot contacts returns invalid_input.

Give a copied folder an honest experiment scope; a title named standing_balance
does not implement balance. Rebuild and verify a real run, repeat/refinement,
perturbation, artifacts and required rendering before calling it executable.

## Visualization input contract (0.6)

A folder cannot execute a custom Blender script or register anatomy by prose.
The trusted renderer currently restores the saved-state contract of the seven
named dynamic backends listed by list_render_profiles. Changing a scenario ID
alone does not add renderer support. New backend support needs reviewed state
reconstruction, coordinate/time/unit checks and real Blender E2E. Preserve original
scientific outputs; make rendering a separate job from an immutable computed run.

Before implementing or accepting human exercise motion, follow the repository
[reference-first rule](../../AGENTS.md#human-movement-references-before-implementation).
Search for real people performing the named variant, open the actual images or
video frames, and record viewed phases/angles and source URLs before choosing
the trajectory. Compare model limits with those references; preserve an honest
negative result if they are incompatible. A numeric PASS is not a technique PASS.
For push-ups explicitly inspect bilateral pectoral forces/activation; rendering
colors must remain computed values and cannot be supplied from expected EMG.
