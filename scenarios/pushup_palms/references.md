# Evidence and interpretation

- Pinned source: https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/ms_human_700
- MuJoCo muscle/transmission equations: https://mujoco.readthedocs.io/en/3.17.0/computation/index.html
- Youdas et al. (2010), conventional push-up EMG: https://pubmed.ncbi.nlm.nih.gov/20664364/
- Marcolin et al. (2015), shoulder/trunk/arm EMG: https://pmc.ncbi.nlm.nih.gov/articles/PMC4732391/

These studies motivate attention to pectoralis major, triceps, serratus and trunk
stabilizers. No EMG signal is used to fit or manufacture activation. Dimensionless
model activation cannot be compared numerically to normalized surface EMG without
matching subjects, electrode sites, filtering, normalization, muscle aggregation,
kinematics and load. Force impulse ranking is a model measure, not an EMG ranking.
Anatomical groups use literal source prefixes; unknown identifiers remain unmapped.

Wrist comparison: https://pubmed.ncbi.nlm.nih.gov/28684196/
Source hand geometry and routes come from the pinned manipulation variant. Finger postures are rigid; this is not a ligament or digital motor-control model.

## Actual chest-level motion revision (2026-11-11)

Full-amplitude follow-up (2026-11-11): the user accepted the chest-level hand
placement and requests straight arms at the top, descent and return. Before
changing the trajectory, ACE top/bottom photos and Intziegianni Figure 1(c)
were reopened and visually inspected again. The wide example starts with
extended elbows and lowers the torso as a unit; palms keep their floor position.
ACE's exercise-library upward phase explicitly finishes at elbow extension:
https://www.acefitness.org/resources/everyone/exercise-library/41/push-up/
No measured joint angles or 3D pose are inferred from these photographs; the
return is not pictured. The initial diagnostics preserved the accepted 70 cm
placement and native ranges before separately testing the derived wrist envelope.

The native-bound continuation and a larger independent-coordinate solve both
approached the native `flexion`/`deviation` limits before elbow extension. These
are preserved as negative kinematic diagnostics, not proof of human infeasibility.
An explicitly separate wrist-envelope experiment is justified by Kim et al.,
*Contributions of the Radiocarpal and Midcarpal Joint in Flexion-extension Motion
of Wrist*, JKOA 2006, DOI 10.4055/jkoa.2006.41.2.315:
https://jkoa.org/DOIx.php?id=10.4055/jkoa.2006.41.2.315
The primary abstract was read on 2026-11-11: five healthy adults (ten wrists)
were imaged at neutral and 30/60/90 degrees extension. This establishes that
90-degree whole-wrist extension was examined, not a universal safe limit or a
subject calibration. It also shows phase-dependent radiocarpal/midcarpal shares;
the native equal-coordinate coupling is not experimentally validated by it.
The first separate engineering-envelope trial fixed -pi/4 radians
for each native flexion coordinate (the other coupled carpal coordinate keeps
its native 1:1 relation); the native bound is -0.6. Only the extension side is
changed in that trial; muscle strength, other anatomical ranges, support points
and acceptance thresholds were retained. Spatial wrist extension must be
measured separately: two oblique model hinges are not a clinical wrist angle.
This derivative is a literature-informed sensitivity experiment, not a correction
to the pinned source files or proof of a calibrated wrist/ligament model.

The equal -pi/4 coordinate trial did not close the full cycle. A coordinate is
not the whole-wrist angle: the native axes are oblique and coupled. The final
coordinate box (-0.930016 lower bound for `flexion_r/l`) was instead derived by
root-solving 90-degree geometric shaft extension across a 21×21 grid of the
unchanged native deviation and pro-supination domains. The shaft runs between
the native elbow and proximal-wrist anchors; its projection in the hand's
longitudinal/dorsal plane is measured independently at every integration step.
The final acceptance cap is 90 degrees plus 0.01 rad numerical margin. This
operational geometric proxy still lacks subject/clinical calibration, and the
source carpal coupling and muscle curves remain unvalidated for this envelope.

The final full-cycle reference uses the **standard-width** variant shown in ACE,
not the previous 70 cm wide variant: 31.0 cm between actual support centroids,
13.3 degrees of hand yaw, palms in the shoulder/chest band. These numbers are
engineering choices solved for this model, not photo measurements. The support
locations are selected jointly for top, intermediate and bottom poses, then held
fixed. Thirty-three checked poses span 0.1–1.9 rad elbow flexion; body posture
coordinates remain within 0.1 rad. The original wide partial experiment is
preserved as `chest_level`. The source-bound rejection and failed separate-pose
attempts remain negative diagnostics; only the separate derivative is eligible
for a full-cycle claim after actual dynamics/contact/muscle checks.

### Historical v1.4 native-range partial motion, preserved as chest_level

The user required a visible change in the rendered motion, not another replay of
the rejected forward reach. ACE side photographs and Intziegianni Figure 1 were
reopened and visually inspected before changing the motion. Figure 1(c) supplies
the real wide-palm variant; its width is not inferred numerically from the photo.
The new engineering reference uses 70 cm between palm supports and keeps both
palms in the shoulder/chest band, about 3 cm caudal to the shoulders in its lower
seed. This is explicitly a wide-palm, partial-range experiment, not a substituted
standard full push-up. Native joint ranges and muscle force parameters are retained.
The bounded reference currently spans native elbow coordinates 1.4–1.90775 rad;
the fully extended upper pose remains unavailable. Every muscle force/activation
must be recomputed from the new dynamics, and all new palm videos must use its
states. Previous wrong-pose videos belong only in a clearly separate archive.

## Human visual references reviewed before this revision (2026-11-11)

- ACE, Brett Klika, *Two Classic Exercises Everyone Should Master* (2016):
  https://www.acefitness.org/resources/everyone/blog/5983/two-classic-exercises-everyone-should-master/
  Actually viewed the two original photographs, `...Master-01.png` (top) and
  `...Master-02.png` (bottom), side/oblique view of a real demonstrator. Observed
  a straight trunk, palms near the shoulder projection, forward fingers, flexed
  elbows at the bottom, and fixed support locations. The return is not shown.
- Intziegianni et al. (2026), *Electromyographic Activation of the Pectoralis
  Major and Triceps Brachii Muscles During Standard, Diamond, and Wide Hand
  Position Push-Ups*, DOI 10.3390/muscles5010018:
  https://www.mdpi.com/2813-0413/5/1/18
  Actually viewed Figure 1, real participant photographs from the front at the
  start and bottom for all three variants. The standard variant (a) has forward
  fingers and hands near shoulder width; diamond and wide are separate variants.
  Pectoral/triceps EMG sensor placement is visible. There is no return frame.

The user clarified the target on 2026-11-11: **palms at shoulder or chest level**.
The head is not a placement target. Distinguish actual palm supports from wrist
origins and fingertips. ACE and Figure 1 were opened and inspected again for this
revision; ACE's exercise instructions also explicitly put shoulders over hands:
https://www.acefitness.org/resources/everyone/exercise-library/41/push-up/
Numerical position tolerances are engineering choices, not measurements extracted
from a 2D photo. The placement comparison projects actual palm pad centres onto
the floor along the pelvis-to-shoulder heading. Its allowed longitudinal band is
between the native caudal Sternum mesh extent and the ipsilateral shoulder joint,
with a declared 5 cm comparison tolerance. This is an engineering interpretation
of shoulder/chest level, not registered human kinematics or a clinical norm.
The reviewed ACE technique puts wrists below shoulders and fingertips toward the
head. In Marcolin 2015's methods, a 20 cm anterior wrist shift is explicitly a
separate forward variant; its figures are graphs, not a visual demonstration.
Do not move the supports arbitrarily forward just to close IK. Retain native
joint ranges and record a negative experiment if a reference cannot be reached.

Review copies and SHA-256 are in ignored `outputs/pushup-human-references/`. ACE
images are linked rather than redistributed as repository assets. The paper's
Figure 1 is available from the publisher; source/licence must accompany reuse.
The photos establish visual technique context, not subject registration or
experimental validation. Published EMG must not be used to manufacture model
activation. Record all six native `PECM1`–`PECM3` paths bilaterally, their forces,
activation, length/velocity and work, with phase and aggregation definitions.

### Historical native-bound probes before the separate full-profile derivation

The legacy reach fails the shoulder/chest comparison. The earlier head-level
probe was the wrong target for the clarified task; its original script is retained
under ignored `outputs/pushup-reference/palm_reference_probe-head-level.py` with
the original pose data. Its failure is not evidence about the corrected task.
`scripts/palm_reference_probe.py` now separately targets actual palm centres at
the shoulder projection and native sternum centre, with forward fingers, flat
palms and unchanged native joint ranges. Local bounded solves and an additional
18-start diagnostic have not produced an accepted upper pose. This is a
model/solver diagnostic, not proof of human or global infeasibility. Those native
experiments retain their original limits and failures. The later full profile's
two changed bounds are separately identified above; muscle strengths remain unchanged.

## v0.8 atlas visualization review (2026-11-21)

Reopened the two ACE side photographs and Intziegianni Figure 1(a) using local
review copies. The side photographs show extended elbows at the top and a
lowered chest with bent elbows at the bottom. The study's frontal photographs
show a shoulder-width placement and outward elbow movement on descent. The
sources show top and bottom only. The return frame is available in the model
playback. The atlas review uses saved `chest_full` states and leaves the motion,
supports and solver parameters unchanged. [ACE photographs](https://www.acefitness.org/resources/everyone/blog/5983/two-classic-exercises-everyone-should-master/) ·
[Intziegianni et al., Fig. 1](https://www.mdpi.com/2813-0413/5/1/18)

In the v0.8 saved-state review, both model palms remain near the upper torso
with forward fingers. The body lowers and returns as a unit with visible
elbow flexion. The model's oblique projection and rigid bones obscure parts of
the palm-floor interface, and elbow paths and toe spacing differ from the
frontal photos. The run's fixed-point support diagnostics provide the
stationarity test. The photos lack a measured floor projection, time
alignment, a matching subject rig and a return frame.

## Closure media review (2026-11-22)

The standard-width ACE start and bottom side photographs and the start and
bottom panels of Intziegianni Figure 1(a) were visually compared with saved
indices 0, 55 and 110 of the four-view replay. Arms extend at the top and
return, with chest descent and visible elbow flexion at the bottom. The exact
bone and palm orientation remains model-specific. The frontal study shows
closer toes than the model, and the oblique scientific camera does not
resolve equivalent frontal elbow angles. Support stationarity comes from
the saved model contact diagnostics. The human sources offer no matched
return image or timestamp. This closure only changes the presentation.
[ACE start and bottom](https://www.acefitness.org/resources/everyone/blog/5983/two-classic-exercises-everyone-should-master/) ·
[Intziegianni et al., Fig. 1(a)](https://www.mdpi.com/2813-0413/5/1/18)

## Contact geometry review (2026-11-26)

Reopened the original ACE top/bottom photographs and Intziegianni et al. Figure
1(a), standard-width flat-palm push-ups. The ACE side view shows extended arms
at the top, elbows bending on descent, the palm remaining in the chest/shoulder
region and the forefoot supporting the body. The study's front view shows
forward, spread fingers and elbows moving outward at the bottom. The photos
do not provide an underside or return frame, metric finger angles, or a
contact-pressure distribution. Foot spacing differs between the examples.
The contact experiment reuses the existing frozen reference and rigid finger
geometry. Proxy clearance, joint targets and comparison thresholds are
engineering inputs. See [ACE](https://www.acefitness.org/resources/everyone/blog/5983/two-classic-exercises-everyone-should-master/)
and [Figure 1](https://pub.mdpi-res.com/muscles/muscles-05-00018/article_deploy/html/images/muscles-05-00018-g001.png).

## Distributed palm and digit contact follow-up (2026-11-26)

Reopened the ACE side photographs (top and bottom) and Intziegianni et
al. Figure 1(a), both frames of the standard-width variant. Both show
the palm heel down below the wrist and the fingers opened toward the
head. In the frontal photograph the thumb sits on the medial side,
separated from the index in the plane of the hand. The elbows move out
as the chest lowers. The sources do not resolve pressure under any
digit, hand thickness, the underside or the return.
[ACE photographs](https://www.acefitness.org/resources/everyone/blog/5983/two-classic-exercises-everyone-should-master/)
· [Figure 1(a)](https://pub.mdpi-res.com/muscles/muscles-05-00018/article_deploy/html/images/muscles-05-00018-g001.png)

Use separate bilateral targets for the palm heel, radial and ulnar
sides, distal palm and digits I–V. Report actual native bearing forces
by region and digit. Test whether the thumb is abducted in the plane of
the palm and near the other fingertips in depth, without any digit
being the sole support. Central palm arch conformity is a geometric
observation, not a requirement for uniform tissue pressure.
Chuckpaiwong and Harnroongroj measured named palmar regions in human
push-ups. Their reported regions guide the measurement partition.
Their peak pressures are not calibration data for this model.
[Palmar pressure study](https://pubmed.ncbi.nlm.nih.gov/19644626/)
