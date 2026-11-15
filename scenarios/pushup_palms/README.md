# Full-amplitude chest-level palms and recorded muscles

Version 1.5 uses `palm_technique: chest_full`: roughly shoulder-width palms,
31 cm between supports, modest 13° hand yaw, with a checked 0.1–1.9 rad elbow
reference and common floor support points throughout. The separately declared
wrist envelope changes only the two flexion-coordinate extension bounds.
A geometric whole-shaft extension gate is checked at every integration step;
this is literature-informed engineering, not clinical/subject calibration.
Source strengths, other joint ranges and internal equalities are unchanged.
All muscle and wrist forces must be recomputed and every main palm video must
use the new states. `chest_level` retains the former native-range 70 cm partial
motion; `legacy_reach` reproduces the rejected older reach.
See [references](references.md) and [current evidence](../../docs/demo/README.md).

`pectorals.csv` records six native PECM paths, including excitation, activation,
signed transmission force, length, velocity and power for every saved sample.
`pectorals.json` records engine-step force impulses and signed work. Use
`camera_view: chest`, layers `bones, pectoral_muscles`, and inspect the separate
`plot.png`. Forces describe their particular model experiment;
they must not be reported as validated ordinary push-up muscle recruitment.

Full primary 700-muscle body with source-derived rigid palms finger posture, genuine detailed hand meshes and 48 source hand transmissions. Native wrist dynamics and multi-point hand contacts are measured. Bounded external residual joint assistance stabilizes the engineering reference; this is not pure muscle-driven control, finger dynamics or ligament tissue simulation. Read separate acceptance gates.

Use `render_result` with `arm_muscles`, `lumbar_muscles`, `abdominal_muscles`, `hand_tendons`, `hand_contacts` and bones. `camera_view: hands` produces a wrist/hand close-up. `wrists.json` and series.csv contain actual ground wrenches and native joint coordinates/torques. `control: muscle` is available as a separate unassisted experiment; never infer successful movement from computed execution alone.

Defaults use `support_boundary: fixed_points`, 0.5 ms integration and a 4.4 s
settle/cycle/hold. Hands and toe contact projections stay fixed in the floor
plane; wrist, ankle and toe coordinates still integrate. Free vertical guides
retain unilateral native floor normals. Require `stationary_supports=PASS`
(0.5 mm maximum drift across every integration step) and numerical friction
checks; a positional constraint alone is not proof of sufficient friction.
See [the derivation](../../docs/HAND_DETAIL.md#fixed-supports-and-moving-wrists).
