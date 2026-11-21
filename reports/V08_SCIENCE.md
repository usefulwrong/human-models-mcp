# v0.8 science handoff

**Release gate: PARTIAL.** v0.8 adds a reproducible illustrative anatomical
surface and a per-claim Evidence Contract. Anatomical verification of the
attachment and an external Fit3D comparison remain open.

The implementation starts from public v0.7.1, Git
`c5bf297463333ee380573f0f96cb3ae5bdf941cc`. Physics remains CPU MuJoCo 3.17.0.
MS-Human-700 is pinned at `98a70c569c4c1b6da467a20012f766ee1f8dc521`,
asset SHA-256 `a32fc82227aebf5156d9efd067d3799513044a24ca12dd117d8b9b4be436d689`.
The old model files and adapters, force and work definitions, and authored
trajectories are unchanged. Source artifacts from the renderer are compared
byte-for-byte. The original v0.7.1 historical reports retain their scope.

The Evidence Contract reports execution status, model pin and engine, scenario
and inputs, code SHA-256, control mode, check status and available thresholds,
anatomical mapping, comparison status, scope and claim class. Evidence
queries for an unsupported tissue quantity return `unsupported`. The narrow
external cadaver comparison remains scoped to the wrist benchmark's two
moment-arm RMSE claims. The atlas report relates only to the render.

## Computed palm-push-up observations

`pushup_palms` uses the existing `chest_full` derivative, external residual
joint assistance and prescribed fixed horizontal guides. It passed the recorded
kinematics, support, numerical and full-push-up gates. The muscle-driven gate
is `NOT_ACHIEVED` with assistance. Chest excursion was 0.279 m and maximum
support-point displacement about 0.095 mm. The flags apply to this computed
trajectory, model contacts and controller.

Phase observations from saved samples 0, 55 and 110 (0, 2.20 and 4.40 s).
Activation is the arithmetic mean of the named actuator paths and
`Σ|F|` is the sum of the magnitudes of signed native path forces.
It is a route aggregate. Start precedes recruitment and settling.

| Source paths | Start activation / Σabs(F) N | Bottom activation / Σabs(F) N | Return activation / Σabs(F) N |
| --- | --- | --- | --- |
| Right `PECM1_r`–`PECM3_r` | 0 / 0 | 1.000 / 1252.65 | 0.00198 / 2.45 |
| Left `PECM1_l`–`PECM3_l` | 0 / 0 | 1.000 / 1253.14 | 0.00084 / 0.95 |
| Bilateral `TRIlong`, `TRIlat`, `TRImed` | 0.00000 / 0.00 | 0.96767 / 3983.80 | 0.54181 / 1761.16 |
| Bilateral `SerrAnt*` | 0.00000 / 17.06 | 0.22845 / 716.96 | 0.02433 / 106.87 |
| Bilateral `rect_abd_*` | 0.00000 / 0.00 | 0.12320 / 158.34 | 0.22117 / 284.97 |

Saturation at the bottom is a model/controller observation. The separate atlas
surface carries no force or activation signal. All 700 source routes retain
excitation, activation, force, length, velocity, power and work accounting.

[Anatomy registration](V08_ANATOMY_REGISTRATION.md) ·
[Reference benchmark](V08_REFERENCE_BENCHMARK.md) ·
[Render verification](V08_RENDER_E2E.md) ·
[Release checks](V08_RELEASE_CHECK.json)

The baseline and final push-up checks measured a maximum repeat-state
difference of zero and a maximum restart-state difference of zero.
The independent sparse transmission reconstruction differed by at most
(1.14\times10^{-13}) in the native generalized-force units. Eleven palm
numeric artifacts, including all six chunks of the 700 muscle traces,
match their freshly computed v0.7.1 hashes.
