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

## Closure review of the current checkout

The closure review began at `8c4293386bb290b5733ab62ff1bd0387d0defdf9`.
The four-view demonstration uses run `042a4b7e-95a0-4b1b-b0d2-4965a23f1861`,
scenario `pushup_palms` 1.5.0, MuJoCo 3.17.0 on CPU, and model asset
SHA-256 `a32fc82227aebf5156d9efd067d3799513044a24ca12dd117d8b9b4be436d689`.
An independent run with the same defaults produced identical metric values
and identical `trajectory.npz`, `series.csv` and `pectorals.csv` digests.

The model completed 8,800 integration steps at 0.5 ms. The start, bottom
and return occur at saved indices 0, 55 and 110, at 0.0, 2.2 and 4.4 s.
The lowest-chest displacement is 0.279 m. `full_pushup` and
`numerical_bounds` are `PASS`; `muscle_driven` is `NOT_ACHIEVED`;
`external_control` is `USED`. The declared sticking guides and residual
joint assistance affect interpretation. [Scenario and criteria](../scenarios/pushup_palms/README.md)

| Saved phase | Pectoral force R / L (N) | Pectoral activation R / L | Triceps activation | Lumbar activation | Abdominal activation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Start | 0 / 0 | 0 / 0 | 0 | 0 | 0 |
| Bottom | 1252.65 / 1253.14 | 1.000 / 1.000 | 0.968 | 0.126 | 0.031 |
| Return | 2.45 / 0.95 | 0.0020 / 0.0008 | 0.542 | 0.0068 | 0.035 |

Pectoral values use the three source bundles `PECM1`, `PECM2` and `PECM3`
for each side. Force is the sum of each path's absolute transmission force.
Activation is the arithmetic mean of the named paths. The other group
activations use the aggregates defined in the run's actuator inventory and
series columns. The pectoral saturation at the bottom belongs to this
controller and model. See the saved signed path forces, excitation,
activation, length, velocity and work in the original run. Surface EMG,
anatomical load, tissue deformation and risk remain outside these measurements.

The negative zero-strength and low-friction legacy trials completed
integration and failed `full_pushup` and `numerical_bounds`. The acceptance
map is preserved in the run evidence and in render evidence. A request for
`computed_muscle_strain` returns `unsupported`.
