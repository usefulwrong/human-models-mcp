# Anatomy, evidence and motion references

## Render an anatomical layer from saved states

The [research workflow](V08_WORKFLOW.md) supports bilateral Z-Anatomy rectus
abdominis via `pushup_rectus`. It uses the same queue and saved states as the
BodyParts3D pectoralis recipe below. Both surfaces are illustrative.

Build the runtime and renderer as described in [Getting started](GETTING_STARTED.md).
Install the optional BodyParts3D subset into `render_jobs/.bodyparts3d` from
the project directory. The network fetch runs on the host. The renderer and MCP
runtime use the verified cache offline.

```sh
PYTHONPATH=src .client-venv/bin/python -m human_models_mcp.visualize provision-atlas \
  --accept-license CC-BY-SA-2.1-JP
PYTHONPATH=src .client-venv/bin/python -m human_models_mcp.visualize provision-atlas \
  --accept-license CC-BY-SA-2.1-JP --offline
make render-start
python3 scripts/visualize.py render --run-id RUN_UUID --recipe pushup_anatomy \
  --frames 7 --device cpu --wait --output outputs/palms-atlas
```

Set `--source-dir` to a folder with the three locked OBJ copies for an offline
import. Replace `RUN_UUID` with a computed `pushup` or `pushup_palms` run.
On a working NVIDIA host, use `make render-gpu-start` and `--device gpu`.
The passport records actual device, fallback and timing. The native MuJoCo
model and state files supply all poses and measured actuator values.

In MCP, use `list_render_profiles` then call
`render_result(run_id, recipe="pushup_anatomy", options={"frames": 7})`.
Use `get_render_job` and `get_render_artifact` for status and hashed file chunks.
The other recipes are `pushup_scientific`, `pushup_muscle_paths` and
`pushup_cinematic`. Set `profile` or bounded options to choose quality.
Recipes use the existing render queue and may reuse an identical successful
or active job. An identical request without an explicit idempotency key can
retry a failed job. The Python equivalents are `rendering.render_result` and
`atlas.provision_atlas`.

The current recipe uses a fixed red surface for the right clavicular part of pectoralis major
(FMA34690). Registration uses separate rigid fits to the clavicle and humerus
and distance-based two-bone skinning. Frame sampling includes the recorded
start, lowest chest and return states. `anatomy_registration.json` reports
vertex-fit residuals, approximate attachment gaps and triangle crossings.
The overlay is `illustrative`. The material is a fixed atlas colour;
the archived purple demonstration predates this display change. See the
[BodyParts3D asset notice](../notices/BODYPARTS3D.md).

## Evidence Contract 1.0

Use `get_result(run_id, claim_id="metric:<name>")`, `"gate:<name>"` or
`"artifact:<name>"`. The full `acceptance` map preserves categorical
statuses such as `NOT_ACHIEVED`, `USED` and `NOT_VALIDATED` in both model and
Blender contracts.
Use `claim_id="all"` for full enumeration, or the local CLI command
`python3 scripts/visualize.py evidence RUN_UUID --claim-id metric:NAME`.
Python exposes `evidence.get_evidence`. Ordinary `get_result(run_id)` returns
the original manifest shape. Each completed Blender job provides `evidence.json`
alongside `passport.json`.

The top-level context applies to each claim. It records model pin and asset digest,
engine, scenario and input parameters, source code SHA-256, control mode, run ID,
named gates and scope limitations. Older runs may have an unavailable code digest.
`computed_status` records execution. `anatomical_mapping_status` records what
geometry or model quantity was observed. `reference_comparison` names the
dataset and observable if available. `validation_status` remains `unvalidated`
for general human biomechanics. A numeric or geometric PASS supports the
named check. The contract returns `unsupported` for absent claim IDs. It
does not estimate probability, clinical safety, strain, stress or EMG.

## Optional Fit3D comparison

Request a licensed personal copy from the [Fit3D project](https://fit3d.imar.ro/fit3d)
and read the [terms](https://fit3d.imar.ro/legal). Use one `joints3d_25` JSON
sequence from a floor push-up and identify one repetition in the matching
video/annotations. Store the raw and derived material outside the project tree.
The reference module is local. Shared MCP and Blender artifacts contain no
Fit3D trajectories or subject information.

Create a JSON metadata file with your release version, subject identifier,
`motion` set to `pushup`, `phase_frames` set to the three **zero-based**
start/bottom/return frames, `world_to_zup` set to a proper signed 3×3 axis
permutation, `coordinate_system` describing the source convention, `unit`
set to `m`, `camera` set to `world`, and `floor_z_m` set to the floor height
after the axis conversion. Establish the rotation and floor from the capture
calibration. The reader checks position ranges, phase order, orientation and
limb continuity.

In a Python 3.12 environment with this package and the pinned model installed,
run `human-models-visualize compare-fit3d RUN_UUID --dataset-json INPUT --metadata
METADATA --private-output NEW_PRIVATE_FOLDER --accept-fit3d-terms`. Python
exposes `reference_motion.import_fit3d` and `reference_motion.write_comparison`.
In Docker, mount the operator's private input directory read-only at a path
outside `/app`, and a separate private output parent read-write. Use
`python -m human_models_mcp.visualize compare-fit3d` in the runtime. Omit the
dataset to obtain `NOT_RUN: LICENSED_DATA_NOT_PROVIDED`.

`comparison.json` reports 13 matched centres, one bounded uniform scale from
limb lengths, start-heading yaw, XY offset, initial alignment residual, MPJPE,
bilateral elbow segment-angle RMSE, shoulder midpoint height and the explicit
time scaling. `reference_overlay.png` shows both skeletons in two projections
at the three simulation phases. This is a descriptive kinematic comparison.
Motion capture alone cannot establish tissue loads, activation or injury risk.

See the [moving-atlas release gate and source reference preview](V08_MOVING_ATLAS.md).
