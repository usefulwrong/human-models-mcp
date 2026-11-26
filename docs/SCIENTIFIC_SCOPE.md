# Scientific scope

This toolkit computes bounded, model-specific experiments with CPU MuJoCo 3.17.0
and pinned MS-Human-700 assets. `computed` means execution finished. A named
numerical PASS is not human experimental validation. No clinical or exercise
safety interpretation is supported.

## Current flat-palm experiment

`pushup_flat_palm` saves 111 samples from the integrated motion over 4.4 seconds. It uses
700 native actuator paths, articulated fingers, compliant palm patches
and fingertip capsules, frictional floor contacts and external joint
assistance. In the current replay the distributed palm-and-digit criterion
passes. The full cycle, four supports, stationary supports and numerical
bounds fail. An execution can complete with one or more failed criteria.

The two lower wrist-flexion limits are explicitly derived. The associated
90° shaft-angle envelope is an engineering check. Model space angles,
contact proxy patch geometry and controller loads do not supply clinical
joint ranges or skin pressure. [Contact model](CONTACT_MODEL_AND_LIMITATIONS.md)
[Scenario sources](../scenarios/pushup_flat_palm/references.md)

The original `pushup`, `pushup_palms` and `pushup_knuckles` remain available
for explicit reproducibility requests. The fixed-points palm and knuckle
routes prescribe horizontal sticking. Their saved acceptance applies to
their own controller and boundaries. [Historical hand methods](HAND_DETAIL.md)
[Current demo evidence](demo/README.md)

## Quantities and units

| Output | Meaning | Unit |
| --- | --- | --- |
| Joint coordinate / velocity | Source hinge coordinate / rate, not a clinical angle by default | rad / rad s⁻¹ |
| Slide coordinate / velocity | Source translational coordinate / rate | m / m s⁻¹ |
| Excitation, activation | Native actuator input and dynamic state | dimensionless |
| Transmission length / velocity | MuJoCo actuator route, not separate muscle-fiber or tendon strain | m / m s⁻¹ |
| Signed actuator force | Native transmission force; pulling is negative | N |
| Mechanical power / work | Signed transmission force × route velocity / its time integral | W / J |
| Floor / guide reaction | Model contact and numerical boundary reactions | N |
| Ground moment about wrist | Contact lever-arm sum, not an internal joint reaction | N m |
| Moment arm | `−∂L/∂q`, or stated coupled derivative | m (radians dimensionless) |

Path activation colors use saved values. They are not surface EMG and do not
show tissue volume. A group mean is the arithmetic mean of its named paths;
summed path-force magnitudes are not a net chest or joint force. The six bilateral
PECM1–3 paths are reported explicitly. Passive/generalized constraint forces
are not discrete ligament tensions.

## Other bounded experiments

- `elbow_sweep`, `knee_sweep`: static coordinate slices; `mj_forward`, zero
  elapsed time, other coordinates fixed. Derivative checks do not establish
  physiological joint motion.
- `knee_coupled`: a local path enforcing eight source knee equalities. The
  wider 0.2–1.0 rad path is rejected because a dependent source coordinate
  exceeds its own bound. This is a model-definition conflict.
- `activation_pulse`: at most 50 ms of uncontrolled muscle forward dynamics,
  without a floor or equilibrium initialization.
- `loaded_elbow`, `elbow_tracking`: explicit soft pelvis fixture and prescribed
  external torque or joint PD control. Their reference is synthetic.
- `wrist_benchmark`: ten neutral-wrist moment arms compared with nonimpaired
  cadaver aggregate means/SD in Nichols, Bednar and Murray (2016),
  [publisher article](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0157346).
  The CC0 publisher XML/extraction are retained under `benchmarks/`. This is a
  narrow comparison, not validation of the whole model or push-up dynamics.
- `standing_contact_probe`, `assisted_stance`: short locomotion-variant native
  contact transients. The latter has explicit external pelvis support. Neither
  implements independently balanced human stance.

## Unsupported claims

No diagnosis, treatment, injury probability, ligament mechanics, deforming skin,
validated volumetric muscle mechanics, organ function, fatigue, patient anatomy, sex/age
customization or medical clearance is available. Joint limits and numerical
thresholds are source/settings, not human population norms. The 85 primary
coordinates include coupled coordinates; 700 actuators are model subdivisions,
not 700 independently validated anatomical structures.

Use `get_model_capabilities` before requesting a quantity. Unsupported requests
return structured refusals without fabricated substitutes. Source search returns
attributed references, not newly computed biological facts.

The optional anatomy recipes show a right clavicular pectoralis surface from
BodyParts3D or bilateral rectus surfaces from Z-Anatomy. Registration is
illustrative. Fit residuals and geometry transfer checks accompany the
render. Native muscle-path activation and atlas surface shading describe
different quantities. The local Fit3D workflow compares geometric observables.
[Anatomical replay and Evidence Contract](ANATOMICAL_EVIDENCE.md)
