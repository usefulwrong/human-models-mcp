# Experimental palm floor contact

## Current articulated whole-palm experiment

`pushup_flat_palm` uses `articulated_palms_v1`. It restores 22
source digit coordinates per hand, including thumb CMC motion and the
coupled fourth/fifth CMC motion. The 700 actuator identities and strengths
remain pinned. Finger tendon sites move with their native links. The
source digit joint limits, stiffness, damping and armature are copied.
The primary hand mass, centre of mass and inertia tensor at the neutral
assembled pose are preserved by allocating one quarter of the donor
child inertials and assigning the remainder to the hand root. The articulated
hand has configuration-dependent inertia during motion.

The pose fit displaces the thumb radially and aligns the fingertips with
the plane in the hand frame. Finger contacts use fitted source skin
capsules. Six compliant spheres per hand cover the heel, thenar and
hypothenar heel regions and the radial, central and ulnar distal palm.
The ulnar distal sphere moves with the fourth metacarpal. These are
discrete contact regions with engineering dimensions. The pads have
zero mass, are floor-only and react through the actual native body.
The external controller contributes bounded joint torque to orient the
wrists and keep the fingertips near the floor. Recorded hand motion and
contact deformation remain distinct from deformable skin and clinical
pressure.

`palm_regions.json` gives native normal force for each palm region and
digits I–V and records the digit angles and peak applied digit torque.
The distributed-contact gate requires at least 0.25 N at every named
region in at least 95% of assessed saved states after 0.2 s. Step-clock
contact histories permit independent continuous-time sampling checks.
Whole-body motion, especially toe slip and numerical bounds, is assessed
separately. [Flat-palm human references](../scenarios/pushup_flat_palm/references.md)

The saved `articulated_palms_v1` replay records `full_pushup=FAIL`,
`external_control=USED`, `muscle_driven=NOT_ACHIEVED` and
`skin_contact_pressure=NOT_MODELED`. Its run summary reports 56.10 mm
maximum support landmark drift at the left toe, 0.02307 rad maximum
hinge-limit violation and 669.14 J of applied external-joint work.
The current MotionScene records two excluded illustrative extensor
indicis surfaces that cross the floor by up to 16.12 mm. The omission
applies to the moving display. The saved motion, physics and failed checks
remain part of the run. [Current scene and render receipts](demo/README.md)

The browser contact inspector retrieves the same exact sample receipt
as MCP `get_contact`. The receipt carries the selected part, state
hash, original acceptance, model parameters, proxy wrench and
source hashes. Skin pressure remains explicitly unavailable. A normal
force alone gives no universal mechanical or injury classification.
[Left and right hand close-ups](demo/README.md#visible-geometry-and-contact) ·
[Scientific quantity receipt](SCIENTIFIC_QUANTITY_CONTRACT.md)

## Historical contact configurations

`pushup_palms_contact` 1.0.0 runs the 700-actuator primary model with the
existing 33 frozen chest-level targets. It integrates the state under
gravity for 4.4 s. The initial pose is shifted vertically once to put the
lowest collision surface 0.2 mm above the plane. The controller applies
bounded joint torques, including posture and hand orientation feedback and
a static load-sharing estimate for bias compensation. The estimate acts
only through joint torques. Native contact events supply the measured ground
wrench. The model has 42 source joint equalities and no support-guide bodies
or world-connect equalities.

The historical `pushup_palms` 1.5.0 uses the legacy assisted boundary
`fixed_points`. Its vertical guides partly prescribe tangential stationarity.
Historical evidence, motions and actuator signals describe that experiment.

## Collision representations

| Profile | Support geometry | Floor clearance |
| --- | --- | --- |
| `surface_spheres_v1` | One massless 4 mm sphere per visible rigid hand and foot bone, at its reference-pose floor-facing extreme | 1 mm beyond the extreme at that pose |
| `surface_convex_v1` | One massless MuJoCo convex mesh collision geom per visible rigid hand and foot bone | Geometry shares the native mesh transform with zero added thickness |

The floor accepts bit 8. Only the new floor-only proxies emit that bit.
Source self-collision and source masses, inertias, muscle curves and the
archived chest-full joint bounds remain as before. The old pad positions
remain inert markers for the existing reference and controller. Selected
skull, jaw, sternum, pelvis, patella, humerus, radius and ulna meshes also
have floor-only convex guards for unintended contact. Ribs and many other
surfaces still have incomplete collision coverage.

Both recipes use condim 3, the existing pyramidal friction convention,
nominal sliding friction 0.8, solref 4 ms/1 and solimp
[0.95, 0.99, 0.001, 0.5, 2]. The final recipe sets floor and proxy margins
and gaps to zero. The 1 ms comparator changes only the timestep. The 0.15
comparator changes only sliding friction. These settings and the 2 mm
visual target and 5 mm hard limit are engineering choices. They have no
clinical interpretation.

## Contact data and display

The per-run `contact_manifest.json` maps source visible IDs to collider IDs,
native bodies and joints. It records the right-handed Z-up metre frame, floor
pose and masks, collider pose, size and solver parameters. It links the saved
state clock, signed nearest vertices, native event chunks and gzip chunks of
integration-step floor wrenches. The integration index reports impulses as
right-endpoint sums of recorded native forces. Contact event force coordinates
follow the engine convention. World force on the supported body is opposite
the force on geom 1 when the floor is geom 1. A reported center of pressure is
a proxy computed from the net wrench, and a monitored marker's drift includes
body rotation and rolling.

MCP `get_contact` accepts a run UUID, a mapped geom or body, and exactly one
saved index or time in seconds. The response carries the sample hash, signed
geometry distances and native floor events. Requests for skin pressure or
ligament forces yield structured `UNSUPPORTED`. Legacy data remain available
through the existing run and artifact calls.

The Anatomy Explorer MotionScene builds the floor from the experimental model
and binds the existing illustrative atlas to the newly saved states. Browser
playback selects discrete source states in the experimental clip. The
**Debug contacts** checkbox is off by default. It shows the collision
envelopes, cyan native load-bearing normals and red skeletal surface depth
markers. The same GLB objects are present in the Blender OVERLAYS collection.
The state index, time and state SHA-256 identify each sampled observation
across both consumers. Transparent debug envelopes can occlude some surfaces
in screenshots. Neither consumer projects visible vertices onto the plane.

The natively fitted hand has detailed source phalanges baked into a rigid pose.
The musculoskeletal atlas is an illustrative display layer. The contact recipe
does not model skin, soft tissue pressure, independent finger dynamics or
ligament loads. See the [standard-width human pose references](../scenarios/pushup_palms/references.md)
and [scientific scope](SCIENTIFIC_SCOPE.md).

