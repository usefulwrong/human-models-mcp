# v0.8 render end-to-end verification

The test path uses the official MCP SDK to compute a `pushup_palms` run, queue
`pushup_anatomy`, repeat the submission with the same key, poll, and download
the scene, PNG, GIF, MP4, native data and evidence through hashed chunks. The
independent CLI submits the same recipe and downloads a separate export.
The Blender runtime consumes immutable saved states via OpenUSD and writes
checked atlas shape keys into the editable scene. Falsification cases preserve
their original inputs and diagnostic artifacts.

CPU and GPU are measured separately. Docker enumerated an NVIDIA GeForce RTX
3070 Ti with 8192 MiB and driver 595.99.02. Blender 4.5.15 LTS
(`5afeabba6097`) enumerated that device for both OptiX and CUDA. The renderer
records selected Cycles device, resource limits and fallback. MuJoCo always
runs on CPU.

The baseline and updated projects are run in separate clean directories using
the same pinned model and Docker dependencies. The v0.8 renderer verification
image reuses the clean baseline's installed and hash-verified Blender stack.
The package and runtime environment are then rebuilt with the v0.8 source.
The phase contact sheet is checked alongside the human references. The original
reported movie stays in the historical demo. [Rendering recipe and CLI instructions](../docs/V08_ANATOMICAL_EVIDENCE.md)

## Compatibility and request cost

Both the legacy layer list and a named recipe require one render submission.
Using compact JSON with the same run ID and seven frames, the scientific
submission occupies 101 bytes with a recipe or 161 bytes with explicit
profile and layers. The anatomy submission occupies 98 or 155 bytes,
respectively. This excludes the transport envelope. Polling and hashed artifact
downloads still scale with job duration and artifact size. The SDK run logs
separately capture control and metadata payloads, excluding binary chunks.

The public checkout lacks `V06_BASELINE_NUMERICS.json`, so the historical
`make visual-regression` gate reported a missing fixture. The separate v0.8
audit compares 18 stdio/HTTP runs against a newly executed v0.7.1 baseline.
All 18 maximum metric differences are zero. Diagnostic MJCF text for elbow
runs agrees after normalizing the temporary E2E asset directory; the original
bytes and hashes are preserved.

Actual discovery metadata occupies 7,065 bytes in v0.7.1 and 8,266 bytes in
v0.8, including the recipe inventory and anatomical source record. The
submission saves argument bytes while the discovery response grows.

## Recorded results

The final SDK replay used run `951c61c9-c5ef-4292-b62c-8170476d4c21`.
CPU job `38054263-7b72-4cc0-8c7c-17bff55fb71c` and OptiX job
`a66778c1-79e5-42b0-86a5-129993ad3c87` each produced seven frames at
960 × 540 and eight samples. Blender worker wall time was 53.1 s on CPU
and 39.7 s on OptiX. The OptiX run sampled 2,039 MiB device-wide peak GPU use
and completed without fallback. These are per-run observations.

The CPU and GPU reports contain identical registration diagnostics, 36
byte-identical scientific snapshot files and the same frame/state hashes.
The standalone CLI also downloaded an OptiX atlas render and a full-body
scientific render from that run. The separate audit reopened both Blender
files, verified world vertices and mesh topology, checked frames against the
source NPZ, and decoded the MP4 and GIF clocks. Wrong scale, axis rotation
and reordered frames were detected. The final visual review pairs source
indices 0, 55 and 110 with ACE's side photographs and the study's front-view
Figure 1(a). The model's support fixtures, toe spacing and elbow paths remain
model-specific, and the photographs supply no return frame.

Controlled failure tests detected corrupt or missing trajectories, missing
models, incompatible model and engine pins, Blender crash, timeout and
interruption. They verified unchanged source artifact bytes and persistent
failed-job records. A separate three-frame atlas job injected GPU OOM after
device enumeration, retried successfully on CPU and preserved all 36
scientific snapshot files. The failure was injected; physical exhaustion
was not forced.

The separate GPU smoke suite also passed three 51-frame Blender regressions
for elbow tracking (scientific and cinematic) and assisted stance
(scientific). It matched CPU source archive digests for identical model
parameters.

## Closure checks on the current code

The starting checkout was `8c4293386bb290b5733ab62ff1bd0387d0defdf9`.
The isolated Docker installs used Python 3.12, MuJoCo 3.17.0, the locked
Blender 4.5.15 LTS archive and OpenUSD 26.11. Model provisioning verified all
251 locked files from a local cache. The native science run and four
views are documented in the [study demo](../docs/demo/workflow/README.md).

The official SDK exercised one combined request and the equivalent separate
requests for calculation, named evidence and four recipe submissions. In the
61-frame run, the combined path used **1 call**, 283 compact JSON argument bytes
and 3,445 result bytes. The separate path used **6 calls**, 869 argument bytes
and 77,007 result bytes. These measurements exclude discovery, queue polling,
media download and protocol envelopes. The separate requests reused the same
run and jobs. [SDK verification example](../examples/mcp-client/research_client.py)

A CPU run completed all four recipes with seven selected saved states each.
An independent OptiX run on RTX 3070 Ti replayed 61 saved states for the
regional atlas, with no fallback. Device-wide sampled memory peaked at
2,500 MiB out of 8,192 MiB during that job. The seven CPU atlas state hashes
occur in the GPU run in the same order. All 36 source snapshot digests agree
and the original inputs were rehashed after rendering. The prior right
clavicular pectoralis recipe also completed its separate three-frame CPU
CLI check.

The independent check reopens the standalone Blender scene, verifies saved
state and frame hashes, audits native geometry and atlas vertices and tendon
face assignments, and decodes the entire MP4. The check rejects wrong scale,
axes, frame order and a rectus geometry scale fault. The native and MP4/GIF
regression tests use the actual encoded frame clocks. Source-state playback
has no image interpolation. The shorter CPU check uses a coarse preview
clock. The demo uses 61 saved-state renders at 14 fps.

The Docker science suite retained the existing tests, SDK transports and
scenario regressions. Eighteen numerical comparisons against the available
historical baseline had zero metric differences. The exact legacy
`make visual-regression` target remains blocked because
`V06_BASELINE_NUMERICS.json` is absent. No historic pass is promoted to a new run.

Controlled negative checks covered source corruption and missing data,
incompatible engine/model pins, wrong geometry/clock, a rejected license
request, an exercise-gate failure and worker crash, timeout and interruption.
An injected GPU memory failure was followed by real CPU render and unchanged
science inputs. Physical device exhaustion was not attempted.

The final verification also ran both commands from `make e2e` separately
on the last code build: the container's stdio/HTTP suite and the fresh SDK
clients both exited successfully. The combined command exceeded the host
session limit. `make test` on that build passed all 105 tests and built and
checked the wheel and sdist. The four public MP4s were decoded and inspected
at intervals across the full cycle. The CPU simulation and OptiX anatomy
media and evidence were retrieved through MCP and matched the published
files by SHA-256. The fresh public source export passed `--strict-tree`
with 264 included files and 33 demo asset checks.

The complete four-view RTX run finished on OptiX, with 61 frames per recipe
and no fallback. The official SDK fetched the media and evidence for each
job and checked equal source clocks and state hashes. The updated scientific
camera was separately re-rendered on CPU and is the scientific view in the
public demo. Media and renderer provenance are recorded per view.
