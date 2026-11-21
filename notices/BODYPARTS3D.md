# BodyParts3D attribution and asset boundaries

The optional v0.8 visual layer uses three pinned BodyParts3D 4.3 objects.
BodyParts3D, © The Database Center for Life Science (DBCLS).

| Object | Representation | Concept | Anatomy |
| --- | --- | --- | --- |
| FJ1447 | BP23304 | FMA34690 | Clavicular part of right pectoralis major |
| FJ3362 | BP23174 | FMA13322 | Right clavicle |
| FJ3368 | BP23164 | FMA23130 | Right humerus |

The local importer takes the asset-specific license of the pinned download
copies, CC BY-SA 2.1 Japan. The current archive license page separately offers
CC BY 4.0 with DBCLS attribution. This project follows the ShareAlike terms
stated for the verified copies. Preserve the notice and license on distribution
of these objects and adapted meshes in the Blender scene and scene archive.
[DBCLS license page](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html) ·
[Pinned mirror's data notice](https://github.com/olivercase/body_parts_3d_api/blob/fd527e6f4daf732fd814314d9257df5877b844bc/LICENSE) ·
[CC BY-SA 2.1 Japan](https://creativecommons.org/licenses/by-sa/2.1/jp/)

The OBJ files remain in the operator's cache. The project ships an asset lock
with object URLs, IDs, sizes and SHA-256. The original simulation archive
keeps the scientific input files. Each atlas render ships the source notice
in `anatomy_registration.json`, the scene metadata and the Evidence Contract.
The MIT license covers the wrapper code.

## Whole-body reference preview

`scripts/atlas_reference.py` uses the separately pinned MyoSuite
`fullbody_atlas_light.glb`, distributed by that project under CC BY 4.0.
BodyParts3D © The Database Center for Life Science (DBCLS), adapted and
rigged by MyoSuite. MyoSuite documents the fitting, weight assignment and
decimation. This project applies a fixed display colour and smooth shading
and hides identifiable papillary cardiac objects in the preview. The
reference rig stays in its source pose.
[Myosuite asset terms](https://huggingface.co/datasets/myohub/myosuite-assets/blob/afa8427188c8bd054925200c70db6757908dee45/README.md)
