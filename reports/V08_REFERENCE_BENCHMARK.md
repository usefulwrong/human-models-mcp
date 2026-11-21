# v0.8 motion reference benchmark

**Fit3D experiment: NOT_RUN — LICENSED_DATA_NOT_PROVIDED.**

Fit3D uses synchronized Vicon motion capture and cameras. Its 50 Hz 3D skeleton
has 25 joints, including the 17-joint Human3.6M skeleton. AIFit includes
floor push-ups. The official reader opens `joints3d_25/<action>.json` and reads
the `joints3d_25` field. The importer maps thirteen of those joint centres.
[Dataset](https://fit3d.imar.ro/fit3d) ·
[AIFit, Fieraru et al.](https://mihaifieraru.github.io/publication/fieraru_2021_cvpr/Fieraru_2021_CVPR.pdf) ·
[Official reader and joint links](https://github.com/sminchisescu-research/imar_vision_datasets_tools/blob/main/util/dataset_util.py)

Terms reviewed on 2026-11-21 grant a personal, single-user, nontransferable
license for non-commercial research, education or artistic work. The license
permits adaptation, prohibits sharing or distributing the software/dataset, and
allows one archival copy. The project requires acknowledgement of licensed
access and keeps raw input and derivative data outside the repository, Docker
images, CI, shared MCP artifacts and release exports. [Fit3D terms](https://fit3d.imar.ro/legal)

The importer checks JSON shape, finite selected joint positions, units,
right-handed orientation, limb dimensions, annotated phase order and the
floor/up convention. The comparison restores pinned MuJoCo states, aligns
headings and initial pelvis XY, matches floor levels and estimates one scale
from the eight limb lengths. The report includes the initial alignment
residual and individual segment scale ratios. It then gives MPJPE, geometric
elbow segment-angle RMSE, shoulder midpoint height RMSE, phase offset and affine
time scaling. The local overlay shows both skeletons at start, bottom and
return. Missing channels include measured tissue loads, EMG and pressure.

The synthetic regression reproduces identity alignment and detects tampered
units, handedness, phase order, NaN and missing license acknowledgement. It
only exercises software. See the
[licensed-data instructions](../docs/V08_ANATOMICAL_EVIDENCE.md#optional-fit3d-comparison).

Alternate candidates reviewed on 2026-11-21. REHAB24-6 explicitly captures table
push-ups and the deposit text restricts use to noncommercial academic/nonprofit
research. CMU catalogues vertical push-ups embedded in a gymnastic trial.
Neither motion was substituted for a standard flat-palm floor push-up.
[REHAB24-6 deposit and terms](https://zenodo.org/records/13305826) ·
[CMU catalog](https://mocap.cs.cmu.edu/search.php)

A second software control restored all 111 real saved model states and
compared the resulting landmark series against itself. The overlay and zero
alignment error exercise the saved-state reader and plotting; they provide no
independent accuracy evidence.
