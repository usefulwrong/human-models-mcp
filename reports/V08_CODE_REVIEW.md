# v0.8 source review and optimization

The review covers the v0.8 changes from v0.7.1 and the callers needed to
release them. The expected load is a local trusted operator, one active
Blender render worker, and up to 128 retained render jobs per queue. The
code paths checked include run manifests, saved-state export, recipe reuse,
artifact transfer, Fit3D import, the standalone atlas workflow and packaging.

## Release fixes

| Finding | Reproduction and resolution |
| --- | --- |
| 1. Source distributions dropped the replay entry point | The package manifest selected Python scripts only. The source distribution now includes Bash scripts, and the package check requires the arm replay entry point. |
| 2. Recipe cache keys omitted the renderer dependency pins | Changing a renderer lock could leave a matching cache key. The new key includes both lock digests. The worker rejects a newly queued recipe with a code or lock mismatch before processing the snapshot. The regression test changes a lock and checks the old job and cache behavior. |
| 3. Invalid clocks could reach motion math | An empty or infinite clock caused an indexing error or could reach reference interpolation. Both comparison clocks now require finite one-dimensional samples. The saved-state importer also checks shape before calling `len`. |
| 4. The render pipeline performed redundant file reads | The manifest was parsed three times and the media digest was computed for both the claim and the artifact record. A single read and a single digest per artifact now produce both records. The snapshot reuses the verified digest of each copied file. The actual SDK client checks exact claim and artifact metadata equality. |
| 5. The local atlas path loaded excessive geometry and rebuilt collision trees | The HD step now loads the 62 requested source objects. The fold-repair stage reuses the existing per-frame bounding-volume trees, which are spatial indexes of the triangles. The ordered comparison and acceptance rules are preserved. |

The checks are tied to [the tests](../tests/test_v08.py),
[the render worker](../src/human_models_mcp/render_worker.py), and the
[standalone replay](../scripts/atlas_arm_replay.sh).
In two matched-input Docker runs, fold-repair elapsed time changed from
112.67 to 102.14 seconds. The 23 per-frame reports matched exactly. Loading
only the requested HD surfaces reduced the intermediate Blender file from
57,502,287 to 33,369,971 bytes. Its registration report matched exactly.
These are measurements from this machine. The
[publication report](V08_PUBLICATION_CHECK.json) records the runtime and
artifact checks.

## Remaining evidence limits

The release can report the named numeric and geometry checks. The larger
atlas remains an engineering visualization. It is delivered separately from
the supported MCP pectoralis recipe. There is no independent matched human
push-up validation and no material or tissue stress model in this release.
The historical visual regression fixture is unavailable in the public tree.
The earlier v0.8 audit compared 18 fresh v0.7.1 and v0.8 SDK runs instead.
[Earlier comparison evidence](V08_RENDER_E2E.md)

## Closure acceptance from four perspectives

| Perspective | Observed result and remaining limit |
| --- | --- |
| MCP developer | The 14-tool surface is preserved. An optional typed visualization request queues the four views on one calculated run. Status and artifact retrieval use the original tools. A missing atlas produces a partial response with a recipe error. |
| Biomechanics reviewer | Independent repeats reproduced the sampled state and pectoral trace bytes. Numerical, exercise and muscle-only criteria are explicit. The selected demonstration uses assisted control and prescribed supports. The human comparison remains visual context. |
| 3D reviewer | The scientific camera was reframed to keep the head and hand contacts outside the annotation bands. Reopened Blender files were checked for transfer errors, wrong axes, scales and frame order. Bilateral rectus uses source tendon masks and preserves the observed pelvic crossings in its report. |
| First-time GitHub reader | The README starts with four views of one run. Copyable commands cover the CPU path, optional anatomy provision, MCP, and retrieval of checks and media. The full API and attribution live in linked documents. |

The experimental whole-body MyoSuite atlas has broader geometry but retains
the previously reported attachment and intersection limits. Its arm studies
remain separate from the narrower two-surface recipe in the supported queue.
