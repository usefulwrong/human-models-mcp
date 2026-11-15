# Third-party attribution

The wrapper's MIT license does not relicense models, native libraries or meshes.

- **MS-Human-700**: LNS Group, authors credited by upstream as Chenhui Zuo,
  Kaibo He, Jing Shao and Yanan Sui. Menagerie adaptation at commit
  `98a70c569c4c1b6da467a20012f766ee1f8dc521`; the model directory declares
  Apache-2.0. Full unmodified text: [MS-Human-700-LICENSE](MS-Human-700-LICENSE).
  Upstream README and CHANGELOG are retained in the provisioned directory;
  per-file hashes preserve its meshes/XML without modifications. Cite the
  ICRA 2024 paper named in `scenarios/elbow_sweep/references.md`.
- **MuJoCo 3.17.0**: Google DeepMind, Apache-2.0;
  [MuJoCo-LICENSE](MuJoCo-LICENSE). The installed wheel retains its bundled
  third-party notices and dist-info license files.
- **Official MCP Python SDK 2.3.0**: Model Context Protocol contributors,
  MIT, [official repository](https://github.com/modelcontextprotocol/python-sdk).
- **Other Python packages**: exact complete versions/hashes in
  `requirements.lock`; distribution licenses remain installed in the image.
  Build-time `runtime-environment.json` inventories distributions, including
  NumPy, Pillow, Matplotlib, PyYAML, PyOpenGL and the MCP HTTP/Pydantic dependencies.
  Their licenses are independent; inspect the retained package metadata/license
  directories before redistributing a modified dependency bundle.
- **OS/Mesa libraries**: installed from Debian package repositories. Package
  versions are captured in the runtime environment record; package copyright
  and license notices remain under `/usr/share/doc/` in the image.

The model card's license statement was reviewed; the historical provenance of
every original mesh was not independently reconstructed. No motion capture,
patient anatomy scans, generated anatomy artwork or restricted external assets
are added to scientific outputs. OpenSim and MyoSuite are research comparisons,
not redistributed dependencies. The reference art in `.agent-input` is excluded
from Docker and scientific demo artifacts.

The v0.3 loaded-elbow experiment derives the source model in memory by adding
one explicitly recorded compliant pelvis fixture and time-step setting. It does
not modify the downloaded source files. Engine-rendered demo images retain this
model attribution. No HRA, Z-Anatomy, OpenSim, MyoSuite or OpenCOR assets are
redistributed. Matplotlib 3.11.2 and its exact transitive packages are hash-pinned;
their upstream distribution license files remain in the image.

- **Nichols, Bednar and Murray (2016)**, PLOS ONE 11(6):e0157346,
  DOI 10.1371/journal.pone.0157346: the publisher states a CC0 1.0 public-domain
  dedication. `benchmarks/nichols2016_wrist/article.xml` is the publisher XML;
  reference.csv extracts Table 2 nonimpaired means/SD and converts cm to m.
  Provenance, original/derived hashes and attribution are in reference.json and
  LICENSE.md. This does not reuse the separately licensed/registration-gated
  SimTK PDF. No individual raw specimens are redistributed as records.

## v0.5 locomotion/contact extension

The already pinned Menagerie Locomotion XML, native floor and contact assets use
the same retained Apache-2.0 model license/attribution; the source asset lock is
unchanged. Runtime initialization/solver/support recipes and original scientific
figures are wrapper code/output, with upstream model attribution preserved.

BAAI/MS-Human-700 revision 8eac35bb8788a183c9e8698ee1207c1bbe654094 was inspected
for research; its code/model card declares Apache-2.0. A small walking reference
copy was inspected only in ignored research logs. It is not redistributed or
used in runtime; no independent per-clip provenance/license inference is made.
The retained Nichols article/Table 2 remains CC0 with its original hashes.
No new dependencies, external atlas assets or policy checkpoints are added.

## Optional Blender visualization runtime (0.6)

Blender 4.5.15 LTS (GPL-3.0-or-later), usd-core/OpenUSD 26.11
(LicenseRef-TOST-1.0) and their bundled dependencies are separate from the
MIT wrapper. Exact sources, hashes, licenses and redistribution considerations
are in [BLENDER_RENDERER.md](BLENDER_RENDERER.md) and renderer.lock.json.
External atlas meshes are not integrated into distributed demos. HRA reference
metadata/optional cache has CC-BY-4.0 attribution; Z-Anatomy source review found
mixed asset licenses. No general CC permission is inferred for every asset.

## Public Research Preview demo

`docs/demo/` contains new calculation/render outputs from the pinned source
model, not generated anatomy artwork or human-subject recordings. Original
wrapper data, graphs and scene assembly use the wrapper MIT terms; retained
MS-Human-700 geometry/model derivatives remain subject to Apache-2.0. The full
model license, change/provenance records and wrapper license accompany the
standalone scientific-data and scene archives. The source model files were not
edited on disk; in-memory derivatives are identified in `model_recipe.json`.

Rendered images and editable `.blend` files do not contain the Blender program.
No Blender binary is distributed in the public tree or prepared Release assets.
Using Blender to make a picture does not license the picture as GPL. The local
renderer uses the unmodified official Blender binary under its own terms;
redistributing that binary/image would require a separate obligations review.
No external human reference photographs or third-party exercise videos are
redistributed. References link to their original publishers.
