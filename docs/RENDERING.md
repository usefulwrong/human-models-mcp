# Rendering saved scientific states

MuJoCo states and numeric data are authoritative. The optional Blender 4.5.15
worker restores them with `mj_setState` / `mj_forward`, exports animated OpenUSD,
checks the import and bakes rigid transforms for Cycles. It never integrates
physics again. Materials, light, camera and tube radii are presentation settings.
Physics always runs on CPU.

## Run

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make render-build
make render-preview
```

The quick preview computes `pushup_flat_palm`, prints its full-cycle
acceptance, renders five states on CPU and prints a local HTML path. For a previously computed run in the same store:

```sh
make render-start
python3 scripts/visualize.py list-profiles
python3 scripts/visualize.py render --run-id <run-uuid> --profile scientific --frames 23 --device cpu --wait --output outputs/my-visual
```

Replace the UUID placeholder. Both runtime and renderer need the same
`HMM_RESULTS_DIR` if you override it. Use a new destination every time. For the
independent SDK path with explicit resolution, FPS and sample settings:

```sh
.client-venv/bin/python examples/mcp-client/render_client.py --scenario pushup_flat_palm --profile scientific --frames 23 --fps 5 --width 960 --height 540 --samples 8 --device cpu --timeout 900 --output outputs/my-sdk-render
```

This computes a new run; add `--run-id <uuid>` to reuse existing states. It
checks source immutability, idempotency, artifact chunks and PNG/GIF decoding.
No AI account is needed. Large artifacts are retrieved in ≤256 KiB MCP chunks.

## What the picture means

| Layer | Source / interpretation |
| --- | --- |
| `bones`, `native_geometry` | Source meshes and rigid transforms; incomplete anatomy |
| `muscle_paths` | 418 distinct upper-body native transmission routes for push-ups, with actual activation |
| `arm_muscles`, `lumbar_muscles`, `abdominal_muscles`, `hand_tendons` | Overlapping subsets: 170, 236, 40 and 48 paths; do not add counts |
| `pectoral_muscles` | Six bilateral PECM1–3 paths, not a net chest force |
| `hand_contacts` | Contact proxies and saved model floor reactions and moments about the wrists |
| `joint_axes`, `center_of_mass` | Source joint anchors/axes and mass-weighted COM |
| `contact_forces`, `applied_moments` | Contact reactions and separately declared external loads |

Regional cameras are `hands`, `lumbar`, `abdomen`, `chest` and `full_body`.
Hands/chest require the corresponding numeric source records. RGB activation
mapping before AgX is `(0.12+0.76*a, 0.23, 0.8-0.68*a)` for saved activation
`a`. Path tubes are not muscle volumes or separate elastic tendon tissue.
Detailed hand tubes have a 0.7 mm display radius; other regional paths use
1.2 mm. Force arrows scale at 0.0006 m/N, moment arrows at 0.006 m/(N m).
Neither arrow scale nor material color is a physical constitutive property.

Each passport carries the acceptance of its own run. The current articulated
flat-palm replay preserves `full_pushup=FAIL` and its support failures.
Historical muscle, palm and fist runs retain their original acceptance.
The optional `pectoralis_atlas` layer depicts a right clavicular pectoralis
surface with illustrative skinning. Clinical quantities, ligaments and tissue
mechanics remain outside the scope.
[Preset recipes, atlas installation and Evidence Contract](ANATOMICAL_EVIDENCE.md)

## Clock, coordinates and independent checks

World XYZ is preserved, Z up, metresPerUnit=1. `frames.json` maps each rendered
frame to an existing source state, physical time and SHA-256. Integer linspace
selects saved states; there is no invented physical interpolation. Video time
is frame/FPS, which can differ from physical time. GIF delays are quantized to
10 ms and recorded separately. Display interpolation in an editable scene is
not a new physical solution.

At every exported sample, native double positions/rotation matrices, selected
body landmarks and source mesh topology are compared with Blender. Guards are
2e-6 for positions/rotation-matrix components and 3e-6 for landmarks/body
matrices (metres for translations). Only repeated-index/duplicate source faces
are normalized for USD; original vertices and distinct valid triangles remain.

`scripts/verify_visual_native.py` reconstructs source geometry and data.
`scripts/verify_visual_blend.py` independently reopens the baked scene without
the original USD working files and checks sampled transforms/overlays.
`scripts/render_e2e.py` provides `audit_media`, which runs those checks plus
FFprobe timing/dimensions and a complete FFmpeg decode. It does not infer human
accuracy from matching meshes. The [current demo](demo/README.md) includes its saved clock and asset checksums.

## Limits and GPU

Live `list_render_profiles` gives the defaults: preview 480×270/4 samples/CPU,
scientific 960×540/16 samples, cinematic 1280×720/32 samples. Requests bound
width/height, samples, 3–101 frames, 1–30 FPS, 30–900 s and 4 billion
pixel-samples; the number of frames cannot exceed available source states.
One worker serializes jobs. Limits: 128 retained jobs, 128 MiB/file and
512 MiB/job. No automatic cleanup deletes evidence.

On a host with an already working NVIDIA Docker runtime, `make render-gpu-start`
and `--device gpu` request OptiX/CUDA. The actual backend or CPU fallback reason
is recorded in the passport. A fallback is not a GPU success. No host drivers
are installed or changed. The RC's GPU status is separate from the required CPU
checks. No pixel equality between CPU and GPU is promised.

The worker has no network or Docker socket, a read-only root, 8 GiB RAM and
read-only scientific results. Source corruption, crashes, timeout and
interruption fail the job while retaining diagnostics. Read
[Security](SECURITY.md) and [renderer licenses](../notices/BLENDER_RENDERER.md).
No Blender binary or external atlas geometry is shipped in the source repository.
