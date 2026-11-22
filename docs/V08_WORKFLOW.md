# Reproduce a push-up with four Blender views

The default `pushup_palms` scenario uses the pinned MS-Human-700 model, a
synthetic reference, external joint assistance and fixed horizontal guides.
Each view reads the same persisted integration states. The run reports its
exercise, numerical and muscle-only criteria separately.

## Install and provision

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make render-build
make render-start
python3 scripts/visualize.py list-profiles
```

For the `pushup_rectus` recipe, review the license and extract the pinned
Z-Anatomy source. The two selected objects and derivative geometry use CC
BY-SA 4.0. [Source and credits](../notices/BODYPARTS3D.md#rectus-abdominis-supplement)

```sh
mkdir -p outputs/rectus render_jobs
curl -fL https://raw.githubusercontent.com/Z-Anatomy/Models-of-human-anatomy/0a849e8acf7080f8da3251a926fbc160d2bc3f7a/Z-Anatomy.zip \
  -o outputs/rectus/Z-Anatomy.zip &&
echo 'e029688545627bd0214b269e1063143abb580aad72b2c2445d6d8a9a0d9da736  outputs/rectus/Z-Anatomy.zip' \
  | sha256sum -c - &&
unzip -p outputs/rectus/Z-Anatomy.zip Z-Anatomy/Startup.blend > outputs/rectus/Startup.blend &&
echo '9f08a17ea0115fed80b2a73ecdf0a1bc2ab2f6956f37c593ce23d513ea35afcd  outputs/rectus/Startup.blend' \
  | sha256sum -c - &&
docker compose run --rm --no-deps -T \
  -v "$PWD/outputs/rectus:/atlas:ro" \
  --entrypoint /opt/blender/blender renderer \
  -b --factory-startup --disable-autoexec /atlas/Startup.blend --python-exit-code 1 \
  --python /app/scripts/atlas_rectus_blender.py -- /app/render_jobs/rectus.npz
docker compose run --rm --no-deps -T --entrypoint human-models-visualize runtime \
  provision-rectus --accept-license CC-BY-SA-4.0 --source /app/render_jobs/rectus.npz
```

The extraction uses the locked Blender 4.5.15 build and retains two named meshes
and their source tendon face assignments. Provisioning verifies the extracted
NPZ digest and writes the local license receipt. The worker reads these
bounded arrays with pickle disabled. The source `.blend` stays local.
For the older right clavicular pectoralis recipe use
[`provision-atlas`](V08_ANATOMICAL_EVIDENCE.md#render-an-anatomical-layer-from-saved-states).

## Submit the study and retrieve evidence

```sh
python3 scripts/visualize.py research --scenario pushup_palms \
  --recipe pushup_scientific --recipe pushup_muscle_paths \
  --recipe pushup_rectus --recipe pushup_cinematic \
  --options '{"width":720,"height":406,"samples":4,"frames":61,"fps":14,"device":"cpu","timeout_s":900}' \
  --idempotency-key v08-closure-public-cycle
```

This command uses CPU rendering for all four views. The published Anatomy
video used OptiX. The demo manifest preserves the per-view settings.

The response contains a run UUID and one job UUID per accepted recipe. A
`partial` response retains successful submissions and includes a reason for
each rejected recipe. Use a fresh key for an independent physics computation.
Reusing the key with the same scenario and parameters reuses its scientific
run. Identical active or completed render jobs are reused after verifying
source hashes. A failed render can be queued again with the same recipe.

```sh
python3 scripts/visualize.py evidence RUN_UUID --claim-id gate:muscle_driven
python3 scripts/visualize.py status JOB_UUID
python3 scripts/visualize.py download JOB_UUID --output outputs/my-pushup/rectus
```

For a specific view of the same run, use `render` with `--recipe`
`pushup_scientific`, `pushup_muscle_paths`, `pushup_rectus` or
`pushup_cinematic`. Set `--wait` and a new `--output` directory to
retrieve the completed bundle. Pose timestamps are physical model times in
`frames.json`. MP4 playback uses the declared frame rate and the GIF uses
centisecond delays. All rendered frames come from exact saved states. The
sampling includes start, lowest chest and return even if the lowest-chest
sample falls between two regularly selected indices.

## MCP and Python

`run_scenario` is the MCP entry point. Its optional `visualization` object
takes `recipes` and bounded `options`. Request `get_result` with
`claim_id: "all"` for the full contract or `gate:muscle_driven` for the
named criterion. Poll `get_render_job` for progress. Retrieve the passport,
evidence and media through checksum-verified chunks with `get_render_artifact`.

```python
from human_models_mcp.research import ResearchRequest, run_research

study = run_research(ResearchRequest(
    scenario_id="pushup_palms",
    recipes=["pushup_scientific", "pushup_muscle_paths", "pushup_rectus", "pushup_cinematic"],
    options={"device": "cpu", "frames": 61, "fps": 14, "width": 720, "height": 406, "samples": 4},
    idempotency_key="v08-closure-public-cycle",
))
```

Run the [SDK example](../examples/mcp-client/research_client.py) to check
shared frame hashes, fetch the media and measure submission call counts.

```sh
.client-venv/bin/python examples/mcp-client/research_client.py \
  --frames 9 --key sdk-palms-review --output outputs/sdk-palms-review
```

See [MCP configuration](MCP_API.md) for connecting an agent. The MCP server
accepts named operations and bounded options. Asset provisioning and renderer
startup are local operator operations.

## Read the result

The anatomy view shows bilateral rectus surfaces fitted at two landmarks per
side. Its report contains the exact source objects, the pose-site mapping,
translation and scale checks, side checks, and bone triangle crossings.
The floor is hidden in the close-up inspection view. Crossing counts and
endpoint residuals support engineering inspection. The mapping remains
`illustrative`. Fibre shading and source tendon faces carry no activity
signal. Path overlays show native model activation and the numerical archive
holds excitation, force, length, velocity and work where measured.
[Interpretation and limits](V08_ANATOMICAL_EVIDENCE.md)
