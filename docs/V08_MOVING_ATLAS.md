# Acceptance for the moving anatomical atlas in v0.8

The v0.8 release gate remains **PARTIAL**. Closing it requires a moving,
volumetric whole-body atlas with a strict majority of reviewed skeletal muscles
and a reproducible Blender workflow that runs from scripts without an LLM.
The single-muscle render is an engineering demonstration.

## What counts toward coverage

- Freeze an anatomical catalogue from FIPAT Terminologia Anatomica, second
  edition, chapter 4, before tallying results. Record exclusions and absent
  structures. Count a named muscle once per side when paired. Count heads and
  slips as components of the parent. Report whole-body and regional numerators
  and denominators, including superficial and deep layers.
- Count a structure after review of identity, laterality, source and license,
  origin and insertion landmarks, position relative to adjacent bones and
  muscles, and continuity through movement. A passed Blender transform check
  establishes transfer of the registered geometry. Review anatomical placement
  separately using reference images and verified landmarks.
- Compare reproducible anterior, lateral and posterior views, including
  isolated deep structures. For the push-up use the saved start, bottom and
  return states. Retain the observed gaps, non-anatomical interpenetrations,
  and unsupported structures. An additional movement is needed to exercise
  regions with insufficient motion in a push-up.
- The operator must be able to select a region, run a deterministic recipe,
  inspect the named meshes and open the editable animation and review report
  without an LLM. Use fixed anatomical red by default. A separate activation
  mode requires an explicit, reviewed mesh-to-actuator mapping.

The denominator is pending. Surface counts from one asset and actuator counts
from MuJoCo are unsuitable as denominators. [FIPAT TA2, Part II](https://cdn.dal.ca/content/dam/dalhousie/pdf/library/FIPAT/TA2/FIPAT-TA2-Part-2.pdf)

## Visual review and an upstream candidate

On 2026-11-21 we inspected OpenStax Figures 11.23 and 11.25, the prior
three-phase `pushup_palms` sheet, and the MyoSuite anterior/posterior atlas
visualizations. In the textbook the broad pectoralis major lies anterior to
the thorax, with a distinct deltoid covering the lateral shoulder. Deeper
anterior panels show the serratus and subscapularis. Posterior panels distinguish
the triceps heads and cuff muscles. We use the warm red display convention
from these figures. [OpenStax chapter 11.5](https://openstax.org/books/anatomy-and-physiology-2e/pages/11-5-muscles-of-the-pectoral-girdle-and-upper-limbs)

The updated push-up render still depicts only right clavicular pectoralis major
(FMA34690). It uses the original states 0, 55 and 110 with the same registered
shape. At the bottom it remains an isolated strip near the shoulder. Neighboring
muscles and the remainder of the pectoralis major are absent. The approximately
20 mm humeral attachment gap and clavicle crossings recorded in the original
registration still prevent anatomical acceptance. The red material is constant
across the cycle. [Earlier registration report](../reports/V08_ANATOMY_REGISTRATION.md)

The pinned MyoSuite/BodyParts3D GLB contains 416 named surfaces and authored bone
weights for its own skeleton. The reference importer found five papillary
heart-muscle meshes and hides them. The remaining 411 are source geometry awaiting
classification. For example, the file has distinct clavicular, sternocostal and
abdominal pectoralis surfaces and three triceps heads per side. Its clavicular
pectoralis has weights to the clavicle, humerus and torso. Weight membership is
useful for inspection. Confirmation of actual anatomical attachment requires
independent landmarks on the target skeleton. [MyoSuite asset description and attribution](https://huggingface.co/datasets/myohub/myosuite-assets/blob/afa8427188c8bd054925200c70db6757908dee45/README.md)

A preliminary comparison of nine named STL files in the published MyoSim
source and the pinned MS-Human-700 assets found byte-identical right pelvis,
femur and tibia. The other six checks found different bytes with matching
rounded extents. The right ulna also differs in triangle count (396 vs 398).
This motivates testing shared geometry and local axes before transferring
weights. Asset resemblance cannot establish the world-pose or attachment
correspondence. [Pinned MyoSim meshes](https://github.com/MyoHub/myo_sim/tree/5cd36ee4d823bced6cbd7c02424458ed0fefb2b2/myo_sim/models/meshes)

## Run the reference preview without an LLM

Use the Blender renderer image from `make render-build`. The following
command downloads and verifies the pinned 10 MB asset, then prepares anterior
and posterior PNGs, an editable Blender file and a machine-readable inventory
from its authored reference pose. Use `--asset PATH --offline` with a
previously cached copy and `--device gpu` to require OptiX. This preview uses
the pinned imported muscle-only geometry and its rig. The MS-Human-700
registration remains a separate step.

```sh
python3 scripts/atlas_reference.py --accept-license CC-BY-4.0 \
  --output outputs/atlas-reference
```

Use the existing `pushup_anatomy` recipe for the single-structure replay.
The name and colour of its display material are included in the registration
record. [Procedural push-up rendering](V08_ANATOMICAL_EVIDENCE.md#render-an-anatomical-layer-from-saved-states)

## Motion transfer experiment

A diagnostic transfer matched the GLB's 86 bind centers to the compiled
MyoSim reference. After explicit left/right and mesh-name aliases, 60 target
bone meshes had a unique correspondence within the engineering tolerance of
50 µm for symmetric nearest-vertex distance in raw local coordinates.
204 of the 411 candidate surfaces have all their weighted bone influences
covered by those correspondences. The original authored weights drive these
surfaces through saved states 0, 55 and 110. The numerical match establishes
a geometric transfer candidate. The count remains a surface count.

The Blender experiment on OptiX visibly moves the shoulder, upper arms and
legs through the saved cycle. The pectoralis major and much of the rib-cage
and abdominal musculature are missing from the transfer. Their torso bone
correspondences remain unresolved. An independent reopen of the Blender file
found 10, 12 and 10 surfaces crossing the model floor at start, bottom and
return. The deepest crossing at the bottom is 11.7 mm, on the left flexor
digitorum longus source surface (FJ1414M). This failure stays in the motion
report for inspection. The experiment is **ILLUSTRATIVE** and contributes
zero verified muscles to the release gate.

The local experiment stores a reproducible command in
`outputs/v08/atlas-expansion/reproduce-motion.sh`. It uses the cached pinned
MyoSim source and imported GLB, the verified renderer image and the original
run, mounts scientific inputs read-only, and writes all replay outputs to a
new directory. Three frames have exact source-state indices. Interpolated
poses between those frames have no separate review.

The local video mode uses 23 exact saved states at 0.2 s intervals. The
browser viewer opens with the native skeleton and candidate muscle volumes
visible together. It also offers individual skeleton and muscle views and a
biomechanics view with native muscle paths, joint axes, centre of mass, and
hand and ground contact overlays. The Blender Outliner exposes the source
skeleton, atlas volumes and biomechanical overlays as separate collections.
Each native export frame and candidate rig frame must agree on source
index, time and saved-state SHA-256 before Blender builds the scene.
The deepest observed atlas crossing across these 23 samples is 11.85 mm
at source state 45.

```sh
HMM_ATLAS_PROBE_VIDEO=1 bash outputs/v08/atlas-expansion/reproduce-motion.sh \
  outputs/v08/atlas-expansion/video-replay
```
