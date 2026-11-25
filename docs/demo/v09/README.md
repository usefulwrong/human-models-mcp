# Whole-body assisted push-up · v0.9.0rc1

This demo uses a fresh MuJoCo 3.17.0 run of `pushup_palms` on pinned
MS-Human-700. Run `4c510b1a-70da-4b7d-b51e-ba7fad0ecf82` contains 111 saved
states from 0 to 4.4 seconds. The Blender camera is fixed and the animation
shows every second saved state at its 0.08 s spacing, including the last
state. The last image remains visible for one video frame. The browser capture
shows the right pectoralis inspector at exact saved state 55, approximately 2.2 s.

[Whole-body MP4](whole-body.mp4) · [GIF](whole-body.gif) ·
[Inspector capture](pectoralis-inspector.png) · [Run manifest](scientific_manifest.json)

## Signals

[Plot](muscle-signals.png) · [Plotted CSV](muscle-signals.csv) ·
[File checksums and frame clock](assets.json)

At each saved state, the pectoralis traces use `PECM1`, `PECM2` and `PECM3`.
The triceps traces use `TRIlong`, `TRIlat` and `TRImed`. Suffixes `_l` and
`_r` distinguish sides. Activation is the mean across the three actuator
paths on that side. The force plot sums the absolute native transmission
forces across the same paths. Every CSV row uses the clock recorded in the
native simulation.

The assisted run records `muscle_driven=NOT_ACHIEVED`, `external_control=USED`
and `human_experimental_validation=NOT_VALIDATED`. The surface animation uses
illustrative registration and skinning. The plots report model signals.
Validated tissue mechanics and surface EMG are outside this demo.

## Credits

- Native model and bones from MS-Human-700, Apache-2.0. [Model license](../../../notices/MS-Human-700-LICENSE)
- MyoSuite light muscle atlas based on BodyParts3D © The Database Center for
  Life Science, CC BY 4.0. Surfaces are positioned and skinned to the saved
  model states. [Atlas source and license](../../../docs/V08_MOVING_ATLAS.md)
- Bilateral rectus abdominis surfaces from Z-Anatomy © Gauthier Kervyn, based
  on BodyParts3D © DBCLS. The displayed geometry is fitted to saved model
  landmarks. The animation and inspector capture that include this layer
  are available under CC BY-SA 4.0, with the above credits. [Rectus source and license](../../../notices/BODYPARTS3D.md#rectus-abdominis-supplement)

[Anatomy Explorer and replay setup](../../V09_ANATOMY_LAB.md) ·
[Scientific scope](../../SCIENTIFIC_SCOPE.md)
