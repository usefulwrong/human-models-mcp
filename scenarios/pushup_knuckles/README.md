# Source-derived knuckles push-up with muscle recruitment and explicit residual joint assistance

Full primary 700-muscle body with source-derived rigid knuckles finger posture, genuine detailed hand meshes and 48 source hand transmissions. Native wrist dynamics and multi-point hand contacts are measured. Bounded external residual joint assistance stabilizes the engineering reference; this is not pure muscle-driven control, finger dynamics or ligament tissue simulation. Read separate acceptance gates.

Use `render_result` with `arm_muscles`, `lumbar_muscles`, `abdominal_muscles`, `hand_tendons`, `hand_contacts` and bones. `camera_view: hands` produces a wrist/hand close-up. `wrists.json` and series.csv contain actual ground wrenches and native joint coordinates/torques. `control: muscle` is available as a separate unassisted experiment; never infer successful movement from computed execution alone.

Defaults use `support_boundary: fixed_points`, 0.5 ms integration and a 4.4 s
settle/cycle/hold. Hands and toe contact projections stay fixed in the floor
plane; wrist, ankle and toe coordinates still integrate. Free vertical guides
retain unilateral native floor normals. Require `stationary_supports=PASS`
(0.5 mm maximum drift across every integration step) and numerical friction
checks; a positional constraint alone is not proof of sufficient friction.
See [the derivation](../../docs/HAND_DETAIL.md#fixed-supports-and-moving-wrists).

Current default: `knuckle_technique: neutral_tucked` (1.2.0), neutral fist
orientation and elbows alongside the torso. Require `neutral_knuckle_grip`,
`tucked_elbows` and `bottom_depth` as separate acceptance gates. The legacy
flared/backward grip is a rejected negative experiment, retained for replay.
See [the recorded failure](../../docs/HAND_DETAIL.md#neutral-fists-and-elbows-alongside-the-torso).
