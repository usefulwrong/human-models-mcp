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
  without an LLM. Use the red procedural fibre material by default. A
  separate activation mode requires an explicit, reviewed mesh-to-actuator mapping.

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

## Torso expansion

The MyoSim source mesh `torso_geom_1_thoracic12_s` and the MS-Human-700
`thoracic12` mesh have different file hashes and identical sets of 212
distinct local-space vertices. An explicit alias raises the verified
engineering correspondence from 60 to 61 bone meshes. Using existing
authored weights, 288 source surfaces are now replayable. The 84 new
surfaces include all three parts of bilateral pectoralis major, serratus
anterior, external oblique, ascending and transverse trapezius, and
iliocostalis and longissimus subgroups. Landmark review of muscle
attachments and intersections is still pending.

The GLB lacks independent rectus abdominis, internal oblique, transversus
abdominis and latissimus dorsi volumes. A separate Z-Anatomy layer adds two
named rectus meshes. The script bakes the source hierarchy, takes the
centroids of the inferior and superior 12 mm caps and registers them
against saved pubic and sixth-rib model sites `rect_abd_*\-P1` and
`rect_abd_*\-P4`. It applies a proper rotation and a recorded axial scale,
keeps the source mesh topology and checks laterality. Exact agreement at
the fitted sites is an implementation check. The two-attachment pose
model has no independent interior landmarks or tissue mechanics. These
surfaces remain illustrative. The other three structures require separate
registration before inclusion in the moving atlas.
[Z-Anatomy geometry and terms](../notices/BODYPARTS3D.md#rectus-abdominis-supplement)

The abdomen and back inspection views use separate camera and visibility
settings. Reference images inspected on 2026-11-22 include OpenStax
Figures 11.16 and 11.15, showing the medial rectus behind its sheath, lateral
abdominal wall layers, and the trapezius and erector spinae in posterior view.
The user-supplied anterior labelled plate provides a presentation reference.
[Abdomen reference](https://openstax.org/books/anatomy-and-physiology-2e/pages/11-4-axial-muscles-of-the-abdominal-wall-and-thorax) ·
[Back reference](https://openstax.org/books/anatomy-and-physiology-2e/pages/11-3-axial-muscles-of-the-head-neck-and-back) ·
[User reference](https://klev.club/kartinki/chelovek/18493-kartinki-myshcy-cheloveka-46-foto.html)

With the pinned Z-Anatomy `Startup.blend` available at
`outputs/v08/atlas-expansion/core-sources/z-anatomy.blend` (SHA-256
`9f08a17ea0115fed80b2a73ecdf0a1bc2ab2f6956f37c593ce23d513ea35afcd`),
the cached experiment accepts the following commands.

```sh
HMM_ATLAS_PROBE_VIDEO=1 HMM_ATLAS_PROBE_CORE=1 \
  bash outputs/v08/atlas-expansion/reproduce-motion.sh outputs/v08/atlas-expansion/torso-replay
python3 scripts/atlas_core_activity.py PATH_TO_SAVED_PUSHUP_RUN
```

The activity report uses saved activation and native transmission force
from the assisted-muscle run, lists every contributing actuator, and
reports phase values and per-actuator peaks. A group peak is the maximum
over its recorded actuator channels and samples. Human EMG experiments
also record rectus abdominis and back activity in push-ups. They provide
exercise context. This model run has no paired human EMG comparison.
[Freeman et al., surface EMG in push-up variants](https://pubmed.ncbi.nlm.nih.gov/16540847/)

## Superficial clearance comparison

The original scene has visible bone penetrations. The surface audit found
bone triangle intersections on 270 candidate surfaces in each of the three
reviewed phases. Some pairs occur around attachments. The audit records
triangular surface crossings and leaves the interpretation of individual
attachments to anatomical review.

The clearance recipe changes twelve display surfaces, covering bilateral
pectoralis major parts, external obliques and parts of the trapezius.
It uses an anterior and lateral offset for the anterior surfaces and a
posterior offset for the trapezius. The torso axes come from the saved
bilateral rectus landmarks. The offset is bounded at 24 mm and falls to
zero around pectoral path endpoints, the inferior oblique region, or the
medial trapezius strip. The fit preserves mesh topology. The original
surfaces remain available in an archived Blender collection. Skeleton
objects and the recorded model paths retain their original transforms.

Across the twelve surfaces and 23 saved states, intersecting bone–muscle
triangle pairs fell from 83,615 to 37,385. Every fitted surface had fewer
crossing pairs on every saved state. The implementation rejects a replay
with any non-improving fitted surface/frame. An independently reopened
Blender file is used to check the source bone transforms and repeat the
intersection audit at start, bottom and return. Intersection counts are
resolution dependent. Tissue strain, attachment correctness and contact
forces are outside this display correction.

The comparison keeps the same bones, camera, lighting and simulated phase
on both sides. The front detail camera sits below the support plane and
hides the floor in both versions. Deep back, serratus, shoulder, hand
and foot conflicts remain visible in the full scene. The full anatomical
acceptance gate stays open.

The trusted headless Blender scripts are
`scripts/atlas_collision_blender.py`,
`scripts/atlas_clearance_blender.py` and
`scripts/atlas_clearance_render_blender.py`. The fit takes the previous
torso scene, its `work/expected.json` and `rig-binding-alias-probe.json`.
Use the same renderer environment and mount the scripts and saved-state
inputs read-only. A normal fit writes `clearance.blend` and
`clearance.json` to a new destination. The renderer accepts that
standalone scene and can produce the whole saved-state PNG sequence and
three matching inspection stills.

## Default fibre material and moving rectus view

The standard Blender volumetric muscle recipe and the MyoSuite reference
preview use the same procedural fibre material by default. It attaches
coordinates to the undeformed mesh vertices. The direction for other atlas
volumes follows a dominant geometric axis. This is a display approximation.
The scalar activation colour on analytical muscle paths remains a
separate display channel.

For both rectus volumes the longitudinal coordinate comes from their
registered pubic-to-costal axis. The lighter regions use the original
Z-Anatomy `Tendon` face assignments. The pinned source has 6,611 such
faces out of 20,604 on each side. The importer preserves their indices
and verifies loop order before reattaching a source mask to an existing
scene. The render requires no new geometry or measured fibre directions.
[Atlas source and terms](../notices/BODYPARTS3D.md#rectus-abdominis-supplement) ·
[Anatomical reference for tendinous intersections](https://openstax.org/books/anatomy-and-physiology-2e/pages/11-4-axial-muscles-of-the-abdominal-wall-and-thorax)

The browser's rectus view isolates the two registered muscles with the
rib and pelvic skeleton. It shows the same 23 stored states and the same
clock as the combined atlas. Its camera sits below the support plane
with the floor hidden for inspection. The full atlas displays the floor
and neighbouring muscles. The anatomical acceptance status remains
open and the materials carry no physiology or attachment evidence.

To rebuild the paired render, run the trusted Blender script
`scripts/atlas_rectus_blender.py` on the pinned Z-Anatomy `Startup.blend`
with the destination `rectus-source.blend` following the `--` separator.
Then open the clearance scene with
`scripts/atlas_textured_blender.py` and pass a new output directory and that
extracted source file following `--`. Put `scripts` and
`src/human_models_mcp` on Blender's trusted Python path. The two PNG
sequences use source indices 0, 5, …, 110 and can be encoded at 5 fps.

The [upper-limb review](V08_UPPER_LIMB_REVIEW.md) records the remaining
shoulder, elbow and wrist discrepancies, a bilateral distal forearm fit
and the experimental datasets applicable to each region.

For the updated arm layer and reproducible full-resolution replay, see
the [upper-limb review](V08_UPPER_LIMB_REVIEW.md#full-resolution-arm-surfaces-and-remaining-folds).
Across the 411 visible source surfaces in the authored reference pose,
the full-resolution copy reduces the total number of unmatched open
edges from 215,494 to 9,198. The new reference has 286 surfaces without
open edges and 184 with neither open nor nonmanifold edges after exact
coordinate deduplication. This is a reference topology audit.
The 62 arm parts and their topology audits contribute to the engineering
review. The anatomical coverage gate remains open.
