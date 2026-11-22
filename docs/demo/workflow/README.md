# One saved palm push-up in four views

The workflow uses `pushup_palms` 1.5.0, run
`042a4b7e-95a0-4b1b-b0d2-4965a23f1861`, computed on CPU with MuJoCo
3.17.0 and pinned MS-Human-700. It uses a synthetic reference,
assisted muscle control, fixed horizontal supports and a declared wrist
range derivation. The three matched phases are at 0.0, 2.2 and 4.4 s.

| View | Video | Source |
| --- | --- | --- |
| Simulation | [MP4](simulation.mp4) | Native skeleton, joint axes, centre of mass and ground reaction |
| Muscle Activity | [MP4](muscle.mp4) · [GIF](muscle.gif) | Native path geometry and saved activation |
| Anatomy | [MP4](anatomy.mp4) | Bilateral Z-Anatomy rectus fitted to pubic and costal sites |
| Cinematic | [MP4](cinematic.mp4) | Native model under Blender Cycles studio lighting |

The MP4s contain 61 exact saved-state samples at 14 fps. The underlying run
has 111 samples over 4.4 s. Sampling intervals between exported states are
0.04 or 0.08 s; playback uses the declared display clock. The tagged lowest
chest state is guaranteed present. The build uses no image interpolation.
Simulation, Muscle Activity and Cinematic used CPU rendering. Anatomy used
OptiX. The per-view request fingerprints in the manifest identify each job
and its renderer code. All four jobs reference the same scientific manifest.

[Matched phases](phases.png) · [PNG activity plot](plot.png) ·
[Scientific manifest](scientific_manifest.json) · [Time series](series.csv) ·
[Bilateral pectoral traces](pectorals.csv) · [Frame clock and hashes](frames.json)

## Evidence

- `full_pushup` and `numerical_bounds` passed the scenario's declared gates.
- `muscle_driven` is `NOT_ACHIEVED`. The run used external joint assistance.
- Atlas surface transfer passed the named geometric checks. The mapping is
  `illustrative`. Fit residuals and bone crossings are measured against this
  model. The anatomy camera looks from below the support plane with the
  display floor hidden.
- Motion capture, force plate and EMG comparisons were unavailable for this
  run. Human exercise safety and tissue stress or strain are unsupported.

[Render passport](passport.json) · [Evidence Contract](evidence.json) ·
[Registration and per-phase diagnostics](anatomy_registration.json) ·
[Media provenance and SHA-256](assets.json)

## Source and reproduction

The anatomy still, anatomy video and Anatomy row in the contact sheet show an
adaptation of **Z-Anatomy, The libre 3D atlas of anatomy** by Gauthier Kervyn,
based on BodyParts3D by Kousaku Okubo and DBCLS. These depictions of the
adapted Z-Anatomy surfaces are supplied under **CC BY-SA 4.0**. The adaptation
fits the source surfaces to saved model sites, scales their long axis and
adds procedural fibre shading. The MS-Human-700 model is Apache-2.0.
[Atlas credits and pin](../../../notices/BODYPARTS3D.md#rectus-abdominis-supplement) ·
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) ·
[Model license](../../../notices/MS-Human-700-LICENSE)

The licensed optional source files and editable scene are generated locally.
The [reproduction commands](../../V08_WORKFLOW.md) recreate the study and
download the scene, source bundle and exact video frames. All files in this
folder belong to the same experiment. The [earlier demo](../README.md) carries
its original evidence and hashes.
