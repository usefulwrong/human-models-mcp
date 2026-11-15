# Optional Blender renderer dependencies and anatomy references

Blender 4.5.15 LTS Linux x86-64 is an unmodified official upstream binary.
Official binary archive SHA-256 and corresponding source tag URL are recorded in renderer.lock.json.
Blender is GPL-3.0-or-later; its archive includes copyright/license notices and
bundled-library attribution. Corresponding upstream source:
https://projects.blender.org/blender/blender/src/tag/v4.5.15
No Blender binary is committed to the MIT wrapper repository. Renderer image
redistribution must retain upstream notices and applicable source obligations.

OpenUSD usd-core 26.11 is pinned to the official PyPI project's CPython 3.12
Linux wheel. LicenseRef-TOST-1.0 is the Tomorrow Open Source Technology License
1.0 (Apache 2.0 with changed trademark section); retain OpenUSD-LICENSE.txt.
https://github.com/PixarAnimationStudios/OpenUSD/blob/v26.11/LICENSE.txt
MuJoCo 3.17.0 and native MS-Human-700 remain Apache-2.0, as in THIRD_PARTY.md.
FFmpeg and Debian library versions/licenses remain in the image package metadata;
renderer_environment in each scientific passport records installed versions.

The optional HRA knee-female-left v1.3 cache is CC BY 4.0, by Kristen Browne and
Heidi Schlehlein / HuBMAP, DOI 10.48539/HBM892.RGKB.238. visual_sources.json pins
the official geometry, metadata and FMA crosswalk hashes. It is reference-only,
not registered to the solver, not copied into runtime images and not a supported
moving anatomical layer. No atlas geometry is redistributed with wrapper code.

Z-Anatomy was reviewed at d909eb1e89bf47180b575e4dfacce639c90044b8. Its umbrella
CC BY-SA 4.0 and BodyParts3D attribution do not override included NC components
(inner ear CC BY-NC-SA 4.0; kidney CC BY-NC 4.0). No Z-Anatomy asset is downloaded
or included. Registration and per-asset redistribution review remain unresolved.

The [official Blender license explanation](https://www.blender.org/about/license/)
distinguishes the GPL program from generated images, movie files and `.blend`
artwork. Source model and other asset licenses still apply to those outputs.
The RC does not redistribute Blender binaries or Docker images.
