# Human Models MCP 0.8.0 final release audit

**READY_FOR_OPERATOR_REVIEW** · 2026-11-22 · Research Preview

## Candidate

The release retains one four-view palm push-up, the 14 MCP tools, the typed
`run_research` workflow and claim-level Evidence Contract. The README opens
with all four views. The current release notes supersede the early archive
inventory. The workflow documents the exact Z-Anatomy download, extract and
license receipt. The package check now installs both distribution artifacts
offline and imports entry-point modules from each installation.

The internal Codex handoff was moved to the ignored operator folder under
`outputs/v080-final/`. The public export includes the new research modules,
SDK example and four-view demo. Archived science, demo manifests and original
measurements retain their provenance. The Git index and history were left
for the operator. The public branch checked during review was the v0.7.1
baseline; the candidate includes additions from the current working tree.

## Fresh verification

| Check | Result |
| --- | --- |
| `python3 scripts/public_check.py --strict-tree` in the fresh export | PASS. Relative links and anchors, 33 demo assets, nested ZIP/NPZ, privacy patterns and tree inventory. |
| `make build`, `make render-build` | PASS. Pinned Python 3.12 runtime, MuJoCo 3.17.0, MCP SDK 2.3.0 and Blender 4.5.15. |
| `make test` | PASS. Ruff and 105 tests. The updated packaging check was then run from the public source candidate. |
| `make e2e` | PASS. SDK stdio, loopback HTTP, independent clients and result retrieval. |
| `make pushup-e2e` | PASS. Repeat, half timestep and expected failed gates for zero strength and low friction. |
| `make render-e2e` | PASS. Five CPU cases with saved-state geometry, overlay, clock, MP4 and standalone Blender scene checks. |
| Four-view SDK workflow, CPU and RTX 3070 Ti | PASS. One new palm run, four jobs per backend and nine matched frames per job. OptiX was reported for all GPU jobs. |
| CLI and partial MCP response | PASS. Profiles, study reuse, evidence, job status and download. The missing rectus cache yields `partial`, retains a queued native render and preserves `NOT_ACHIEVED`. |
| Wheel and sdist | PASS. Both built from the source candidate and installed offline against the locked dependencies. |

All eight fresh MP4s decoded. Both downloaded rectus bundles passed independent
MuJoCo and Blender checks, including rejection of wrong scale, wrong axis and
dropped-frame controls. CPU and GPU share the source artifact and sampled
state hashes. Checked-in videos were separately decoded at 61 frames each.
Source archive and Python packages are accompanied by a version and SHA-256
manifest in the local `outputs/v080-final/release/` directory.

## Scientific scope and assets

The palm run completed with fixed horizontal supports and residual joint
assistance. Its numerical and full-cycle gates passed, and muscle-only control
remains **NOT_ACHIEVED**. Exercise safety and tissue stress or strain are
**UNSUPPORTED**. Human experimental validation remains **NOT_VALIDATED**.
Real Fit3D comparison remains **NOT_RUN**. Overall atlas acceptance is
**PARTIAL**. Regional crossing and attachment review and independent reference
validation remain for future work.

Concurrent new submissions to the same scientific store can return
`busy`. This occurred when the CPU and GPU clients tried to compute at
once. The GPU retry replayed the completed CPU run using its idempotency key.

Fresh `series.csv` and `pectorals.csv` match the published bytes. The bilateral
groups contain `PECM1`, `PECM2` and `PECM3` with `_r` or `_l` suffixes.
Mean activation is unitless. Force sums use the magnitudes of the three
native path forces per side. The start sample has zero activation and force.
At 2.2 s, mean pectoral activation is 0.999998 on both sides and the right/left
force sums are 1252.65/1253.14 N. At 4.4 s they are 0.001976/0.000844 and
2.45/0.95 N. Mean triceps activation (`TRI` prefix) is 0/0.968/0.542 across
those phases, versus 0/0.228/0.024 for serratus (`SerrAnt` prefix) and
0/0.123/0.221 for rectus (`rect_abd` prefix). Activation is a model variable
and the force sums quantify transmission paths. The raw run retains excitation,
signed force, length, velocity and model-step work.

Start, bottom and return were inspected against the ACE side-view examples
and Intziegianni et al. Figure 1(a) start/bottom photographs. The model
shows a supported descent and return with forward fingers and palms at
shoulder/chest level. Its rigid hand and foot geometry and idealized guides
limit comparison with human contact and balance. The references provide
no matched measured return. [Scenario references](../scenarios/pushup_palms/references.md)

The public source carries the MIT wrapper, Apache-2.0 model attribution and
CC BY-SA 4.0 attribution for the Z-Anatomy depictions. Blender, model meshes
and optional atlas inputs are separately provisioned. Review of external
links found several access or TLS failures on reference sites. The BHaM
catalogue DOI returned 404, so its documentation links to the authors'
data availability statement. [License notices](../notices/THIRD_PARTY.md)

## Repeat and publish

Run from a fresh extracted public source candidate with host Python 3.12 or
3.13. Use fresh output folders and an isolated Compose project for QA.

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
export COMPOSE_PROJECT_NAME=hmm-v080-review
export HMM_RUNTIME_IMAGE=hmm-v080-review-runtime:local
export HMM_RENDER_IMAGE=hmm-v080-review-renderer:local
python3 scripts/public_check.py --strict-tree
make build
make test
make e2e
make pushup-e2e
make render-build
make render-e2e
```

Provision rectus using the pinned workflow, then run the SDK example with
`--frames 9 --key v080-review --output outputs/v080-review-cpu` after
`make render-start`. Run `make render-gpu-start` and repeat with the same key,
`--device gpu --output outputs/v080-review-gpu`. Finish with
`docker compose stop renderer`. For the partial case, submit native and
rectus together in a fresh unprovisioned queue and query
`get_result(run_id, claim_id="gate:muscle_driven")`.
[Exact provisioning and SDK command](../docs/V08_WORKFLOW.md)

From the release directory, run `sha256sum -c SHA256SUMS`. The operator
reviews the staged candidate including the new files and the handoff removal,
checks CI on that exact commit, and creates the commit, push, tag and release.
[Release notes](../docs/RELEASE_080.md) · [Machine-readable verification](V08_FINAL_RELEASE_CHECK.json)
