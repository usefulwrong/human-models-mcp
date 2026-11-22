# Upper-limb realism review

Reviewed on 2026-11-22. The inspection uses the saved assisted-muscle
`pushup_palms` cycle `951c61c9-c5ef-4292-b62c-8170476d4c21`. The phase
images correspond to source states 0, 55 and 110. Measurements sample
23 exact states. The source run includes rigid finger postures, six
mechanical palm pads and external joint control. Human experimental
validation remains open.

## What the images and geometry show

| Region | Observation and measured check | Interpretation |
| --- | --- | --- |
| Shoulder and elbow | The proximal surface is incomplete around the shoulder. The long biceps head is 11.9 mm from its proximal path endpoint at the bottom on both sides. The long triceps head has a proximal gap of 6–11.2 mm across the three reviewed phases. | A path endpoint is a model landmark. The biological attachment footprints and the soft-tissue continuity at the shoulder require separately registered anatomy. |
| Short biceps head | Distances to the distal path endpoints are 76.3 mm at the start and 40.6–41.0 mm at the bottom. The source short-head mesh's authored rig has scapular and humeral weights. | The source model needs a review of the common distal tendon and its connection to both muscle heads. Translating the short-head belly to the radius would alter its anatomical role. |
| Forearm and wrist | At the bottom the right and left extensor indicis have 859 and 898 intersecting bone–surface triangle pairs respectively. Intersections include carpal and finger bones. | Triangle counts locate registration conflicts and depend on tessellation. The distal extensor route needs anatomical guidance through the wrist and around the digits. |
| Palm support | In the images the bones alone look elevated above the floor. At the bottom, each mechanical pad is a sphere of radius 9 mm and its lowest point is 0.094–0.170 mm below the nominal floor. The vertical force sums are 232.4 N right and 239.2 N left. | The model supports weight on discrete pads. Human palm skin and contact-area deformation require separate geometry and experimental data. |
| Missing intrinsic surfaces | The pinned hand abductor of the little finger and palmar interossei are absent on both sides in the moving transfer. Their authored rig has unresolved hand-bone correspondences. | Sparse rendering around the palm combines missing source transfers and visible mesh intersections. |

The visual review compared Suprak et al. Figure 1 and Intziegianni et al.
Figure 1a. The exposed hands of the participants show palm and spread
digits meeting the floor. The upper arm changes orientation in the
descent. The photos constrain visible posture. Suprak's digitized
thorax, scapula, humerus and forearm frames give a stronger basis for
comparing rotations. Future 3D comparisons should use the same
landmarks, axes and rotation sequence. The paper records the
concentric phase under three shoulder-elevation conditions. The photos
provide start and bottom views for posture review.
[Suprak et al., floor push-up, Figure 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC3867095/) ·
[Intziegianni et al., standard variant, Figure 1a](https://www.mdpi.com/2813-0413/5/1/18) ·
[ISB upper-limb coordinate conventions](https://pubmed.ncbi.nlm.nih.gov/15844264/)

The anatomical comparison used Zheng et al. Figure 2. Their rendered
MRI volumes distinguish the hand bones, intrinsic muscles and narrow
tendons through multiple views. Their tendon registration uses sliding
constraints and medical-image validation. Those hand motions are
unloaded poses and grasping examples. Our push-up hand needs additional
weight-bearing evidence. The arm models and papers below fill different
parts of that evidence gap.
[USC hand simulation, Figure 2 and tendon registration](https://viterbi-web.usc.edu/~jbarbic/handSystem/)

## Local forearm refinement

The source MS-Human-700 brachioradialis paths use a humeral origin and
distal radial endpoint, consistent with brachioradialis anatomy near the
radial styloid. A bilateral display fit moves only a 38 mm neighbourhood
of the nearest distal source surface by a tapered offset toward the
saved endpoint. The greatest vertex displacement is 9.27 mm. The mesh
topology and material coordinates are retained. Across the 23 sampled
states the right endpoint gap fell from 12.33 mm to 3.74 mm and the left
gap from 12.53–12.54 mm to 4.23–4.24 mm. All 46 side/frame checks reduced
the gap with no increase in bone triangle crossings. The proximal
endpoint distances agree within 1 µm. This is a model-landmark fit
and the actual attachment footprint remains unverified.
[Brachioradialis anatomy and insertion](https://www.ncbi.nlm.nih.gov/books/NBK526110/)

`scripts/atlas_arm_review_blender.py` takes the existing saved
`.blend` and the matching `expected.json`. It emits bilateral
bone-crossing and endpoint-distance reports. Its fixed `images` mode
builds side and hand views. `scripts/atlas_arm_fit_blender.py` repeats
those audits before and after the local fit and rejects a result with
a worse endpoint gap, increased crossing count or changed proximal
endpoint distance. It preserves the replaced meshes in a Blender
archive collection. Neither script changes MuJoCo state or force data.

## Research sources and data

| Source | What it contributes | Access and limits |
| --- | --- | --- |
| Suprak et al. and An et al. | Traditional floor push-up shoulder/scapula motion and wrist-to-shoulder load measurements. | Published results and protocols provide comparator quantities. Matching raw trials have not been acquired. [Scapular kinematics](https://pmc.ncbi.nlm.nih.gov/articles/PMC3867095/) · [Push-up kinetics](https://pubmed.ncbi.nlm.nih.gov/2334780/) |
| Fit3D | Consistent multi-view exercise poses for palm, elbow and shoulder trajectory comparisons, including push-ups. | IMAR non-commercial research licence. No restricted files added. The fitted outer body and joint tracks do not supply internal tendon surfaces or tissue mechanics. [Dataset](https://fit3d.imar.ro/fit3d) · [Terms](https://fit3d.imar.ro/legal) |
| USC Hand MRI and Zheng et al. | 48 scans from four people in 12 poses. A published example of separate volumetric muscles, tendons, ligaments and bones with image-based tendon routing. | Dataset CC BY 4.0 with USC and author attribution. Research task and loading differ from a push-up. [Dataset and licence](https://viterbi-web.usc.edu/~jbarbic/hand-mri-dataset/) · [Method](https://viterbi-web.usc.edu/~jbarbic/handSystem/) |
| Pallarès-López et al., synchronized reaching | Ultrasound tracks tissue relative to the humerus in triceps and brachialis, with optical motion, EMG and accelerometry. | Figshare CC BY 4.0, record version 1 and README inspected. Reaching provides a tissue-motion test case. No tissue trajectories from this dataset have been compared to the saved push-up. [Data](https://doi.org/10.6084/m9.figshare.31030252) · [Study and code](https://doi.org/10.1038/s41597-026-07019-3) |
| BHaM (Diaz et al.) and Holzbaur et al. | BHaM has 19 elbow, wrist and hand tasks and publishes tables of MRI-derived muscle volume measurements. Holzbaur reports 32 upper-limb muscle volumes in ten healthy adults. | BHaM raw DICOM and segmentations are withheld. Check the dataset and per-model terms before reuse. Volume distributions support size comparisons after normalizing for anthropometry. [BHaM paper](https://doi.org/10.1038/s41597-026-06939-4) · [BHaM catalogue](https://doi.org/10.34740/kaggle/ds/7895310) · [MRI volume paper](https://pubmed.ncbi.nlm.nih.gov/17241636/) |
| MoBL-ARMS, OpenSim thoracoscapular model, MyoSuite | MoBL-ARMS gives benchmarked upper-limb paths and moment arms. Seth's shoulder model reproduces scapulothoracic kinematics and stays explicit about wrapping surfaces. MyoSuite's atlas rendering describes which bones each source mesh requires. | OpenSim's model catalogue lists MIT for MoBL-ARMS. These paths and bone rigs can cross-check anatomical landmarks, moment arms and shoulder motion. Volume deformation needs separate testing. [MoBL-ARMS paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC4282829/) · [OpenSim model catalogue](https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53090607/Musculoskeletal+Models) · [Seth et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6856649/) · [MyoSuite mesh renderer](https://myosuite.readthedocs.io/en/stable/blender_rendering.html) |
| Péan and Goksel | Published upper-limb method for modelling muscle surfaces as membranes within a finite-element simulation. | A method reference for separating surface movement and mechanical simulation. Reuse terms for a target asset require verification. [Paper](https://pubmed.ncbi.nlm.nih.gov/32709260/) |

The next acceptance review should trace the common distal biceps tendon
and the wrist extensor routes independently, verify their attachments
and crossings dynamically, and test a weight-bearing hand with credible
palm and finger contact area. It should compare the shoulder girdle in
ISB frames and distinguish same-subject anatomical data from published
population measurements.

## Repair of arm mesh seams

A further check found a repeatable rendering defect inside individual
atlas meshes. Exactly coincident rest vertices received different
source skin weights. Their posed copies separated by up to 28.31 mm
in the clavicular deltoid and up to 22.85 mm in brachialis. This
produced open seams in parts of the shoulder and elbow.

The repair assigns the same normalized mean weights to each group
of exactly coincident vertices within one named source mesh. It
changes the weights of 47 arm surfaces. Distinct muscles retain
distinct meshes. The evaluated seams close to within 1 µm throughout
the 23 sampled states. The maximum measured residual is 0.30 µm.
Reopening the saved scene confirmed unchanged triangle indices for
all 47 surfaces and unchanged geometry of the 375 other muscle and bone
objects at the three representative phases. The original weights are
available in a separate Blender collection.

The total number of crossing bone–muscle triangle pairs over the
repaired surfaces rose from 309,499 to 311,423. Closing a seam can
introduce or expose triangle crossings in the resulting connected
surface. The counts leave anatomical bone clearance open. A second
trial with dual-quaternion skinning reduced some triceps crossings
and shifted other landmarks or surface regions. The default repair
keeps linear skinning, with only the coincident weight sets adjusted.
The follow-up trial blended 35%, 50% and 65% of the local corrective
displacement around each elbow. None of these fixed blends passed the
no-increase-in-crossings check at every frame on both sides for any
paired triceps head. The added deformation was rejected.

The inspected Z-Anatomy short-head volume also terminates above the
source radius, while its long-head volume reaches the labelled distal
insertion region. Cadaveric data describe separate distal contributions
from both heads in a substantial subset of individuals. The source gap
therefore remains visible pending separate tendon geometry and landmark
review. [Eames et al. distal biceps dissections](https://pubmed.ncbi.nlm.nih.gov/17473142/)

Open the preceding arm-fit scene with the trusted
`scripts/atlas_arm_seams_blender.py` in Blender. After `--` pass the
new output directory and the corresponding `work/expected.json`.
This writes a scene and the full per-frame seam and crossing audit.
The arm review renderer's `elbows` mode draws both sides at the same
saved bottom phase for direct comparison.

## Full-resolution arm surfaces and remaining folds

The follow-up isolated three visible defects in the same 23 saved states.
Exact split vertices can open under different skin weights. An open edge
with no coincident counterpart can come from the source surface. An intact
surface can fold through itself, the skeleton, or another muscle when posed.
The rendered arm at the bottom exhibits all three effects.

Five named right-arm BodyParts3D meshes from the pinned copy have zero
boundary edges after merging identical coordinates for the audit. The light
MyoSuite file has genuine unmatched open edges in those same structures.
At the level of the 62 replayed arm parts, the full-resolution MyoSuite file
reduces the count from 15,692 to 2,636. Forty surfaces then have no open
edges, and 26 of those have no edge with more than two incident faces. These
counts concern topology and use exact coordinate equality. They do not
establish closed tissue at an anatomical interface.
[BodyParts3D archive and terms](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html) ·
[MyoSuite atlas and resolution description](https://myosuite.readthedocs.io/en/stable/blender_rendering.html#anatomical-muscle-meshes)

The moving scene uses the pinned MyoSuite rigged geometry
and its named influences. Full-resolution weighted joints match the
previously bound joint positions within 0.37 µm. Skin-weight equality at
coincident vertices is enforced in each individual mesh. Reapplying the
distal brachioradialis fit to the full-resolution source improves its
radius endpoint gaps at every sampled frame. The final scene measures
3.20 mm on the right and 3.32 mm on the left. The full-resolution change
also changes some nearest-distances to the native path endpoint proxies.
In the unadjusted source upgrade, the greatest rise for the long biceps
head distal path was 4.85 mm. These are recorded geometric offsets, with
the anatomical footprints still unverified.

The local fold repair then limits vertex movement to 4 mm and uses the
same mask throughout the cycle. The repair keeps 57 surfaces. It rejects
a candidate if any saved frame gains self-intersection pairs or crossing
pairs with any one bone or neighboring surface, or if a monitored native
path endpoint gap rises by more than 0.5 mm. It uses the same triangle
indices and source material assignments. This test applies to the bounded
repair within a fixed tessellation. With the added detail, the final arm
meshes have 127.42 m of summed noncoplanar self-intersection segment length
over all parts and frames, down from 186.46 m in the light replay. The sum
for bone intersections is 427.50 m, up from 408.09 m in the light replay.
The same segment-length measure gives no penetration depth or volume and
can include intersections near attachments.

The paired close-ups show substantially fewer slit-like openings in distal
triceps and radial forearm surface regions. Some angular folds, exposed
bone and rib–torso conflicts remain visible. The missing common distal
biceps tendon connection, finger/wrist tissue paths and palm load-bearing
surface remain open. A direct check of the target fourth and fifth
metacarpal mesh aliases found symmetric local vertex differences of
26.38 mm and 25.84 mm, respectively. The target has no corresponding
pisiform mesh. These structures need landmark-based registration before
the related intrinsic muscles can appear in the moving atlas.

### Additional sources reviewed

- Avci and Röhrle Figure 1 visually separates the elbow muscle bellies,
  tendons and aponeurosis on Visible Human-derived geometry. The model
  also uses two labeled elastic guide bands in place of some missing
  surrounding structures. The article is CC BY 4.0. The figure supplied
  a geometry reference and no CAD mesh was imported for this review.
  [Avci and Röhrle, Figure 1](https://link.springer.com/article/10.1007/s10237-024-01821-x/figures/1)
- OpenArm 2.0 Figure 1 and Table I show static elbow flexion with a brace
  and a sensorized handle, with ultrasound at four angles. The study
  supplies image-derived biceps and humerus volumes. The experimental
  loading differs from floor push-ups. SimTK returned HTTP 403 during
  the access and license check. No data from the release were imported.
  [OpenArm 2.0 preprint and data links](https://laurahallock.org/publication/nozikhallock2019embc/)
- Kerkhof et al. describe MRI/CT segmentation and dissection of one
  left forearm, including wrist extensors and intrinsic hand muscles.
  The paper identifies MorphoSource project P419. The project endpoint
  did not provide media terms or files in this session. The article is
  used as a reference for source selection. [Kerkhof et al.](https://doi.org/10.1111/joa.12877)

### Reproduction and status

Run the full-resolution reference importer and the arm replay below in
the repository with a Docker Blender renderer that has OptiX access.
The two middle positional inputs are the existing saved-state mapping and
the new authored reference. The base scene is the earlier seam-repaired
moving atlas from this review.

```sh
python3 scripts/atlas_reference.py --accept-license CC-BY-4.0 \
  --mesh-quality hd --device gpu --output outputs/atlas-hd-reference
bash scripts/atlas_arm_replay.sh BASE_BLEND EXPECTED_JSON \
  outputs/atlas-hd-reference/reference-atlas.blend outputs/atlas-arm-replay
```

The replay writes a separate phase-by-phase registration report, the
distal arm fit, the repaired scene, a reopened-scene audit and an H.264
video. The reopened geometry audit covers 23 samples and confirms the
same native skeletal meshes and 233 other atlas surfaces before and
after local fold repair. Two runs agree on all per-frame repair
metrics. A perturbed humerus orientation and a light asset passed as
the full-resolution source were both rejected. SHA-256 checks pass for
all 36 source files. Blender Cycles used OptiX on an RTX 3070 Ti.
The source run and position/force artifacts remain immutable.
`scripts/atlas_arm_contours_blender.py` reads the scene, expected mapping
and surface-repair report to compare intersections across tessellations.
The moving scene is still **ILLUSTRATIVE**. The limits before v0.8
acceptance remain in the [whole-body criteria](V08_MOVING_ATLAS.md).
