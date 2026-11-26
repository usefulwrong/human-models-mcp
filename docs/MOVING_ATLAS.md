# Moving atlas and source geometry

[Provision Anatomy Explorer](V09_ANATOMY_LAB.md) to query static BodyParts3D
4.3 geometry and its source relationships. Available atlas meshes and FMA or FJ
records are distinct from complete anatomical systems. The complete authored
4.3i inference graph remains unverified.

The current `pushup_flat_palm` MotionScene replays the native MS-Human-700
bones and selected MyoSuite surfaces. The light GLB is pinned to MyoSuite
assets revision `afa8427188c8bd054925200c70db6757908dee45`. Its geometry
derives from BodyParts3D © DBCLS and is licensed CC BY 4.0. Bilateral
Z-Anatomy rectus surfaces have a separate CC BY-SA 4.0 attribution. Model
materials and scene lighting are presentation settings. [Source credits](../notices/BODYPARTS3D.md)
[Original MyoSuite dataset and attribution](https://huggingface.co/datasets/myohub/myosuite-assets/blob/afa8427188c8bd054925200c70db6757908dee45/README.md)

The native poses, GLB and crosswalk are tied to the same run and state hashes.
The builder retains the source identity and measured floor penetration for any
excluded display surfaces. Skin and organs are separate static atlas layers.
The moving mesh does not establish anatomical attachment, tissue mechanics or
human physiological validation. [Current demo manifest and captions](demo/README.md)
