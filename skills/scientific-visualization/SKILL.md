---
name: scientific-visualization
description: Render saved human-models-mcp experiments through the verified Blender Cycles pipeline, select supported layers and quality, retrieve chunked media and interpret the visualization passport without inventing anatomical or clinical evidence.
---

# Saved experiment to scientific media

1. Discover `list_models`, `list_scenarios`, then `describe_scenario` and that
   scenario's `describe_model`. Read `list_render_profiles` for live profiles,
   layers, option bounds and unsupported anatomy. Do not guess available layers.
2. Select `elbow_tracking`, `loaded_elbow`, `standing_contact_probe`,
   `assisted_stance`, `pushup`, `pushup_palms` or `pushup_knuckles`.
   Run the scenario with `parameters={"render":false}` if a new
   experiment is needed, or use an existing successful `get_result(run_id=...)`.
   Require `computed` and a manifest-listed `trajectory.npz`. Other scenarios
   still compute, but do not currently supply this renderer's saved-state contract.
3. Call `render_result` with the existing run UUID. A conservative example:

   ```json
   {"run_id":"<returned UUID>","profile":"preview","layers":["bones","muscle_paths","joint_axes"],"options":{"frames":5,"width":480,"height":270,"samples":4,"device":"cpu"}}
   ```

   For contact choose `bones`, `contact_forces`, `applied_moments` and
   `center_of_mass`. Scientific paths use actual dimensionless activation;
   cinematic colors are explanatory. Force arrows use 0.0006 m/N; applied moment
   pseudovectors use 0.006 m/(N m), not joint reaction estimates. Preview uses
   CPU; scientific/cinematic can use `device="gpu"` or `"auto"`. Discover bounds
   before changing quality. New requests use new UUID jobs; an idempotency key
   retries the same request only. `queued` requires the separate operator-started
   renderer service, never a request to execute Docker inside MCP.
4. Poll `get_render_job(job_id=...)`. Only `completed` has complete verified
   outputs. `failed`, `unsupported` and `invalid_input` are not successful renders.
   A render failure leaves its original physical run unchanged; it does not
   invalidate or upgrade that run's numerical evidence. Do not repeatedly rerun
   physics to repair a rendering problem.
5. Read `passport.json`, `frames.json`, `geometry_validation.json`, then fetch
   `preview.png`, `animation.mp4` and optionally `scene.blend`, `scene.zip` or
   `source.zip`. `get_render_artifact` accepts job/artifact IDs and byte offset,
   never host paths. Request at most 262144 bytes per chunk; verify chunk and
   whole-file SHA-256, contiguous offsets and final byte count. The original
   `get_artifact` remains limited to 2 MiB and serves scientific runs, not jobs.
   Use the public SDK downloader rather than pasting video base64 into context:

   ```sh
   .client-venv/bin/python examples/mcp-client/call_tool.py get_render_artifact \
     --arguments '{"job_id":"<job>","artifact_id":"animation.mp4"}' \
     --trace-dir reports/logs/my-agent --artifact-output outputs/my-animation.mp4
   ```

   This bridge performs real MCP requests and records receipts. The standalone
   equivalent is `python3 scripts/visualize.py render --run-id <UUID> --wait
   --output outputs/my-visual`; use a new output directory. It downloads a local
   index.html, media, scene and scientific passport without a host MCP install.
6. Inspect the image and source numeric data. Cite the source run, exact model
   revision/hash, physical times, physics backend, actual render device and named
   geometry checks. Frames replay saved states without `mj_step`; playback may
   be slowed, with the clock defined by `frames.json`, not video duration.

## Interpretation boundaries

- Native model bones are source meshes with numerically checked rigid transforms,
  not a registered external atlas, complete skeleton or deforming tissue model.
- Tendon paths are lines/tubes with a minimum display radius, not muscle volumes.
  Activation colors describe the saved model state, not observed human activity.
- Elbow tracking has a soft pelvis fixture and external joint servo with a
  synthetic target. Contact support in `assisted_stance` is an explicit external
  pelvis wrench. Neither is an unassisted human movement demonstration.
- Contact arrows depict native simplified collision geometry. They do not certify
  all mesh collisions, sole pressure, balance or safe posture.
- HRA/Z-Anatomy source metadata is discoverable, but `atlas_reference`, `skin`,
  `muscle_volumes` and `internal_organs` are unsupported until registration and
  applicable licenses are checked. Do not create substitute anatomy.
- `computed` is physics execution; `completed` is render execution;
  `validated_for_named_checks` covers specific numeric checks only. Neither
  experimental human accuracy nor clinical validation follows from good graphics.
  The wrist published-data comparison does not validate elbow/contact motion.
- Materials, light and camera are presentation. GPU rendering is not GPU physics.
  Physiology, breathing, defecation, sex-specific customization and medical safety
  remain unsupported. Use [interpretation rules](../scientific-interpretation/SKILL.md).

## Push-up layers (0.7)

`pushup` also supplies this saved-state contract. Include `bones`, `muscle_paths`,
`contact_forces`, `center_of_mass`, `joint_axes`; do not select a locomotion model.
The camera covers the full body, graphs show GRF and calculated activation for
five named groups, and visible native paths use saved activation in every profile.
The editable .blend groups these layers into named collections for toggling.
For media comparisons, render the same run again with a different layer list;
no physics rerun is needed. The demo page switches between such saved-state views.

Inspect all source acceptance gates in the render passport. A completed video
does not upgrade an unsuccessful physical experiment. Read source.zip for all
700 muscle traces and the sparse mechanics. Current push-up `muscle_paths` shows
418 upper-body paths (the original demo contains 26), not anatomical volumes.

## Detailed hands and regional layers

Use `pushup_palms` and `pushup_knuckles` for the two source-derived fixed finger
postures. Defaults use `assisted_muscle`: real muscle forces plus explicit
residual external joint torques. Require `external_control=USED` and do not
describe them as pure muscle-driven, even when `full_pushup=PASS`.

Discover `arm_muscles`, `lumbar_muscles`, `abdominal_muscles`, `hand_tendons` and
`hand_contacts`. Region counts overlap; the upper-body union is 418. Render an
existing run with `options.camera_view="hands"` and layers
`["bones","hand_tendons","hand_contacts","joint_axes"]`; this requires its
`wrists.json`. `lumbar` and `abdomen` camera views expose the regional paths.
The editable scene groups the paths into named collections and stores each
source actuator name. Activation colors remain recorded values.

Hand pads are declared mechanical proxies, not skin pressure. Amber arrows are
per-hand floor forces; purple arrows are ground moments about the wrist,
not internal joint reactions. Fingers are rigid baked source poses; discrete
wrist ligaments, intrinsic hand muscle dynamics and separate elastic tendon
tissue remain unavailable. Native wrist angles are source coordinates, not
calibrated clinical extension angles. Compare the two variants as engineering
scenarios with different reference hand placements, not an isolated causal or
safety experiment. [Details](../../docs/HAND_DETAIL.md).

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

Choose a recipe via `list_render_profiles` and pass it to `render_result` with
bounded options. Use the job and artifact IDs to retrieve `evidence.json`,
`passport.json` and media. Load the atlas only with its pinned license receipt
and retain the separate asset attribution. Read `anatomy_registration.json` for
mesh transfer, attachment gaps and scope. Keep licensed Fit3D inputs and overlays
local. An aesthetic overlay supplies no measured anatomy.

[Anatomical evidence guide](../../docs/V08_ANATOMICAL_EVIDENCE.md)

For the local whole-body review, use the pinned MyoSuite full-resolution
reference and the deterministic arm replay command in the
[upper-limb review](../../docs/V08_UPPER_LIMB_REVIEW.md#reproduction-and-status).
Read the open-edge, native path, and intersection reports alongside paired
renders. Compare triangle-pair counts only for fixed topology. The replay is
an illustrative Blender workflow with the original saved model states.
