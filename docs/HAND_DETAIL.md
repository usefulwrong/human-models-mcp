# Historical fixed-point hand methods and regional measurements

For the current articulated palms and their measured limits, see [contact evidence](CONTACT_MODEL_AND_LIMITATIONS.md).

**Historical fixed-point derivation:** `pushup_palms` 1.5 uses `palm_technique: chest_full`,
chest-level palms at approximately shoulder width (31 cm) and 0.1–1.9 rad elbow
targets. A multi-phase bounded IK plans the entire cycle with common fixed
supports, then freezes 33 checked poses. Only initialization sets a physical
pose; later states still result from `mj_step`. Two wrist-extension coordinate
bounds are explicitly derived, with a separate shaft-angle envelope checked
at every integration step.

`chest_level` preserves the former 70 cm native-range partial trajectory;
`legacy_reach` preserves the rejected forward reach. Neither archive is rewritten.
The neutral tucked-fist trajectory is unchanged.

The full profile changes only `flexion_r/l` lower bounds from -0.6 to -0.930016
rad. The coordinate box was derived offline from 90° projected forearm-to-hand
extension across the source deviation/pro-supination domain. Kim et al. 2006
(DOI 10.4055/jkoa.2006.41.2.315) examined whole-wrist extension up to 90° in ten
healthy wrists. This motivates an engineering envelope, not a calibrated
mapping of the model's oblique coupled hinges to clinical angles. All other
source joint ranges, couplings, mass/inertia and muscle curves/strengths remain.
The geometric proxy uses native elbow and proximal-wrist anchors in the hand
longitudinal/dorsal plane; it is saved independently of individual joint values.
`wrist_extension_envelope` rejects exceeding 90° plus 0.01 rad numerical margin;
`elbow_extension` requires upper start/return elbow coordinates below 0.15 rad.
The immutable packaged reference has its own SHA-256 and is copied into every
run as `palm_reference_input.json`. It is synthetic, not motion capture.

The new `pectoral_muscles` layer and `chest` camera show six native bilateral
PECM1/2/3 paths. New runs save `pectorals.csv` and `pectorals.json`; the client
downloads a separate `plot.png` with right/left force and activation traces.
These measurements describe their source experiment, including rejected poses.
The [movement methods](MOVEMENT_METHODS.md) require real human visual references
before exercise geometry changes and phase-by-phase review.

The extension provides two explicit experiments, `pushup_palms` and
`pushup_knuckles`, using the full primary MS-Human-700 model. The original
`pushup` experiment retains its original mechanics and unassisted muscle mode.
The new variants integrate real muscle excitation, activation and forces with
**bounded external residual joint assistance**. Their `muscle_driven` status is
`NOT_ACHIEVED`, even when the full-cycle/contact/numerical gates pass.

The [current demo](demo/README.md) uses the articulated frictional route.
The commands below create new individual exports under ignored `outputs/`.
Historical comparison viewers and the original 26-path demo are retained in the
private research archive; they are not pre-existing public downloads.

## Muscles and layers

All 700 actuator traces remain available in the scientific archive. The expanded
upper-body display selects **418 distinct native transmission paths**:

| Layer | Source membership | Paths |
| --- | --- | ---: |
| `arm_muscles` | Both native arm XMLs, serratus and trapezius; chest/shoulder/upper arm/forearm | 170 |
| `lumbar_muscles` | Iliocostalis, longissimus, multifidus, quadratus lumborum, psoas and latissimus source prefixes | 236 |
| `abdominal_muscles` | Rectus, external/internal obliques and source `TR1`–`TR5` paths | 40 |
| `hand_tendons` | 24 extrinsic hand/wrist transmissions on each side | 48 |

Membership overlaps: the table must not be summed. `muscle_paths` selects the
union for push-ups; individual layers allow regional inspection. The source
identifiers, region membership and selected counts appear in the passport and
editable scene. `TR1`–`TR5` run through abdomen/lumbar attachments; the previous
trapezius prefix classification was corrected. This literal path mapping does
not establish a universal anatomical ontology.

Every displayed color uses the saved source activation, including cinematic
push-up views. The tubes show MuJoCo transmission routes, **not muscle volumes**.
Hand display radius is 0.7 mm; other regional paths use 1.2 mm, purely for
readability. No inferred or generated anatomical tissue is inserted.

## What changed in the hands

The pinned manipulation model supplies a genuinely articulated right hand and
native mirrored left bone meshes. Its geometry is evaluated in either an open
or curled source-joint posture, then baked into the full model's existing rigid
hand bodies. Each side has 23 source bone geometries. The left posture reflects
the right pose; it is not a separately measured left-hand configuration.

The 48 extrinsic transmissions are rerouted through the manipulation model's
actual sites and wrapping geoms. Native manipulation actuator length ranges are
transferred where supplied; primary maximum forces are retained. The primary
body's mass/inertia, 85 human coordinates, 700 actuators and 42 source equalities
remain intact. Four numerical vertical guides add four coordinates, bodies and
connect equalities for the prescribed sticking boundary (89 coordinates, 85
bodies and 46 equalities in total). The full model is not replaced by the manipulation
variant's simplified torso/lower body.

Palm support has three spherical mechanical pads per hand, at the heel and two
metacarpal landmarks. Knuckle support has two, at the index/middle MCP landmarks.
Pad radius is 9 mm; offsets from bone landmarks are explicit engineering contact
thickness assumptions, not registered skin or measured pressure distribution.
The feet retain the original toe pads. Source wrist joints still integrate;
fingers retain their declared rigid posture without independent grip control.

`hand_support_geometry` additionally requires at least two load-bearing hand
pads in more than 95% of saved post-settle samples per side, and support-normal
tilt below 0.1 rad. The separate `stationary_supports` gate requires **every** hand/toe pad and
prescribed support point to stay within 0.5 mm in horizontal position, measured
at every integration step. The other exercise, force, penetration and numerical
checks remain separate. These are engineering acceptance conditions.

## Fixed supports and moving wrists

The historical fixed-point scenarios use `support_boundary: fixed_points`. One prescribed horizontal
material point per hand and per foot closes the kinematic chain. The reference
is solved with bounded closed-chain IK, keeping full hand orientation and both
toe sphere centres fixed. During integration the controller never overwrites
`qpos`; the rendered hands and feet use the saved native states without clamps.

Each material point uses a MuJoCo [site-based connect equality](https://mujoco.readthedocs.io/en/3.17.0/XMLreference.html#equality-connect)
to a tiny **unactuated, vertically free guide**.
Only its horizontal coordinates are fixed. Native pad/floor collisions supply
unilateral normal support: lifting away from the plane remains possible and
no weld to the floor supplies a pulling normal force. Toe anchors are at sphere
centres; their projections coincide with the floor contact locations while the
ankle and toe joints rotate. Hand pads share one horizontal guide per hand;
there is no separate pin for each pad.

This is a declared **ideal sticking boundary**, not a prediction that arbitrarily
low friction will stick. Actual native and guide reactions are combined per
limb and must satisfy the aggregate Coulomb bound with the configured friction
coefficient, at every step. Native contact cone violations are also checked at
saved samples. Inadequate friction makes `numerical_bounds` and `full_pushup`
fail even if the guides hold the positions. Aggregate bounds do not establish a
calibrated pressure map or a full distributed contact-wrench model.

Each guide has 0.1 g mass (the source compiler minimum), zero armature, a free
vertical slide and 0.01 N s/m vertical damping. Guide inertia/damping and its
small vertical reaction are recorded and included in the human force/moment
balance, without counting them as load-bearing floor normals. The numerical
connect constraints are regularized, so submillimetre residual motion is
measured rather than described as mathematically zero. The initial 20 µm
preload and changed contact/equality solver settings are in `model_recipe.json`.

`support_stationarity.json` reports maxima for all four material points and all
six/eight native pads, point speeds, constraint work and the 0.5 mm threshold.
`support.json`, `wrists.json` and force overlays include actual guide reactions
as well as native floor forces. `series.csv` records instantaneous maximum pad
displacement. A regression runs the former `frictional` boundary and requires
its centimetre-scale drift to fail the current acceptance criterion. Original
`pushup` results retain their historic boundary and acceptance for compatibility.

## Wrist measurements and interpretation

`wrists.json` contains every saved hand contact position and world force, summed
floor force, wrist origin, ground moment about that origin and support normal.
`series.csv` contains their components, bearing-point counts, support tilt and
native flexion/deviation/pronation coordinates plus actuator/passive/constraint
generalized torque components. All timestamps align with the saved integration
states. Force units are N, moments N m, coordinates rad, positions m.

`hand_contacts` renders the mechanical pads, per-hand floor-force arrows
(amber, 0.0006 m/N) and ground-moment pseudovectors (purple, 0.006 m/(N m)).
Moment is the actual sum of contact force lever arms and native contact torque
about the wrist. It is not a measured internal joint reaction. Passive and
constraint generalized torques are not discrete ligament tensions.

Use camera views `hands`, `lumbar`, `abdomen` or `full_body`. The hand view plots
each hand's vertical force and native wrist coordinates. Blender collections
separate bones, regional paths, hand contacts, joint axes and other overlays;
source actuator names remain attached to path objects. New exports use stable
per-tendon segment identifiers as wrapping segment counts change.
Regional cameras fit the selected paths over all sampled states and check their
projected screen bounds. Regional frames show actual mean activation in a caption;
full-body and hand views retain the time plots without covering the regional view.

## Neutral fists and elbows alongside the torso

The current `pushup_knuckles` default is `knuckle_technique: neutral_tucked`
(scenario 1.2.0). Palmar normals face toward each other and radial hand axes
point forward along the floor. The bounded IK reference keeps elbow joints in
the longitudinal planes through the shoulders. Fist positions are 0.40 m apart;
the initial elbow angle is 0.2 rad and the reference peak is 1.9 rad. These are
explicit engineering targets for the requested technique, not clinical norms.
Native shoulder, forearm and wrist ranges are unchanged.

Three separate gates now supplement the cycle/contact checks for knuckle runs:
`neutral_knuckle_grip` requires inward/forward axes within 30 degrees of their
target directions; `tucked_elbows` requires upper-arm flare below 30 degrees
when elbows are flexed beyond 0.6 rad; `bottom_depth` requires shoulders to be
no more than 50 mm above elbows at the lowest chest sample. The geometric
measurements, in metres/radians or dimensionless cosines, are saved in
`series.csv`; maxima and acceptance are in `summary.json` and the recipe.
These targets check the requested posture, not injury risk or human validation.

The old `legacy_flared` recipe remains replayable. It is a **rejected technique**,
even though its old immutable result says `full_pushup=PASS`: those earlier gates
omitted grip orientation, elbow flare and adequate depth. The new gates reject
it. Its native forearm/wrist ranges were approached while adequate descent was
not achieved. See [the useful negative experiment](../tests/fixtures/rejected_knuckle_pose.json).
This records a bad AI-generated reference exposed by constrained mechanics,
including the insufficiency of the old acceptance criteria.

Both new muscle recruitment and all 700 muscle forces are recomputed for the
corrected reference. A change of hand/arm posture changes load distribution;
the display must not prescribe activation based on expected anatomy. Results
remain assisted, and comparison of muscle impulses is not causal inference or
surface EMG validation. The commands below create new exports. No pre-existing private comparison
viewer is required to inspect or reproduce the public demo.

## Comparison boundaries

The current variants use a **4.0 s descent/ascent cycle**, 0.2 s initial settling
and 0.2 s final hold (4.4 s total), muscle recruitment at 100 Hz, **0.5 ms**
integration and explicit residual joint assistance. There are 111 saved states
at 40 ms intervals; stationarity and aggregate friction are checked on all
8,801 evaluated states, including the initial state.
The assistance subtracts current muscle generalized force from requested joint
force along the source equality tangent, saturating the residual at 200 N m.
No root generalized force, pelvis fixture or external body wrench is applied.
Both hand orientations are regulated through native joint torques. Gravity
feedforward uses predicted static load sharing, not measured pad pressure. Foot
coordinates are free of proportional reference feedback, allowing the ankles
and toe joints to articulate while toe contact points stay put. These controller
contributions are part of the reported assistance. Actual residual magnitudes/work are measured in the summary.
Effective gains are in `controller.kp_by_independent_joint`; `controller.kp`
retains the original base value before the detailed-hand overrides.

The unmodified primary wrist flexion range is ±0.6 rad in its native coordinates.
Knuckles and the preserved `chest_level` partial profile retain it; current
`chest_full` uses the separately declared envelope described above. Stances and
wrist envelopes therefore differ: this is **not a controlled causal comparison
of wrist loading**, clinical wrist angles or an injury/safety recommendation.
Earlier unassisted detailed-hand attempts did not meet all gates; the original
unassisted scenario is separately regression tested.

Discrete wrist ligaments, intrinsic hand muscle dynamics, separately elastic
tendon tissue, deforming skin and registered muscle volumes are unavailable.
`wrist_ligaments` returns `unsupported`. Source joint equalities are not a
ligament model. A next tissue-mechanics extension needs identified geometry,
attachments and constitutive parameters with independent validation.

The [MuJoCo muscle documentation](https://mujoco.readthedocs.io/en/3.17.0/modeling.html#muscles)
explains the abstract muscle/transmission model. The
[primary wrist push-up study](https://pubmed.ncbi.nlm.nih.gov/28684196/) motivates
measuring posture-dependent load direction, but supplies no validation of these
model trajectories or ligament forces. See the scenario reference files for
push-up EMG context; activation is not normalized surface EMG.

## Reproduce

Build once and use a fresh scientific store for both the runtime and renderer:

```sh
make render-build
export HMM_RESULTS_DIR="$PWD/outputs/my-hand-science"
mkdir -p "$HMM_RESULTS_DIR"
docker compose -p human-models-mcp-night up -d --no-deps renderer

python3 scripts/experiment.py --scenario pushup_palms --output outputs/my-palms-data
python3 scripts/experiment.py --scenario pushup_knuckles --output outputs/my-knuckles-data
```

Each export prints its run UUID. Render the same saved run repeatedly with
different layers; choose a new output directory for each export:

```sh
python3 scripts/visualize.py render --run-id <palms-run-uuid> --profile scientific \
  --frames 17 --device cpu --camera-view hands \
  --layers bones hand_tendons hand_contacts joint_axes \
  --wait --output outputs/my-palms-hands

python3 scripts/visualize.py render --run-id <knuckles-run-uuid> --profile scientific \
  --frames 17 --device cpu --camera-view full_body \
  --layers bones muscle_paths hand_contacts contact_forces center_of_mass \
  --wait --output outputs/my-knuckles-full
```

Swap the run UUID/camera/layers to inspect the other hand posture or regional
layers. For exact E2E media settings with public MCP SDK transfers, use:

```sh
.client-venv/bin/python examples/mcp-client/render_client.py \
  --scenario pushup_palms --run-id <palms-run-uuid> --profile scientific \
  --layers bones muscle_paths hand_contacts contact_forces center_of_mass \
  --frames 17 --fps 7 --width 960 --height 540 --samples 4 --timeout 900 \
  --output outputs/my-palms-full
```

The client verifies idempotency, immutable source states and transfer hashes.
Historical fixed-support comparisons used Cycles OptiX. Add `-f compose.yaml -f compose.render-gpu.yaml` when starting
the renderer and `--device gpu` to request that backend; CPU rendering remains
available. No system/driver changes or control of other GPU processes is needed.

Checks use the existing Docker tooling:

```sh
docker compose -p human-models-mcp-night run --rm --no-deps -T --entrypoint sh runtime \
  -c 'ruff check --no-cache src tests scripts examples && pytest -q -p no:cacheprovider && python scripts/check_package.py'
```

Downloaded media are additionally checked with `audit_media` from
`scripts/render_e2e.py`: native state/mesh reconstruction, reopening the baked
Blender scene, overlay positions/colors/visibility, video timing and full MP4
decode. Detailed native reconstruction shares the source-hand derivation helper;
it independently checks the resulting state/geometry against Blender rather than
claiming an independent anatomical derivation. Historical hand/fist reports and all source runs are retained in the local
research archive. The rejected-pose fixture remains executable in the unit suite.
