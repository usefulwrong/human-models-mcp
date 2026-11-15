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

Hand-position EMG comparison: https://pubmed.ncbi.nlm.nih.gov/16095413/
This supports remeasuring load distribution after a posture change; it does not
validate this fist trajectory or establish universally disjoint muscle groups.
The neutral/tucked technique and numeric gates are explicit engineering choices.
