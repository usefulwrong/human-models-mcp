# Neutral wrist experimental-reference benchmark

Run `run_scenario(scenario_id="wrist_benchmark")` or
`python3 scripts/experiment.py --scenario wrist_benchmark` after make build.
The named output directory contains a local index.html, CSV, plotted comparison,
reference provenance and all model-derived artifacts, obtained through MCP.

The reference is Table 2 nonimpaired means and between-specimen SD from Nichols,
Bednar and Murray (2016), eight cadaver specimens, published under CC0. Ten
observations cover FCR, FCU, ECRB, ECRL and ECU about extension and ulnar deviation.
Units are converted from cm to m. No individual raw trials or surgery data are used.

Model neutral is found by aligning PCA longitudinal axes of the radius and third
metacarpal meshes. Radial direction comes from fifth-to-second metacarpal centroids;
dorsal direction completes the frame. Positive angles move the distal hand axis
dorsally (extension) and ulnarly. The two source carpal equalities are enforced.
A 2×2 physical-angle Jacobian transforms tendon derivatives to these functional
coordinates. Independent finite differences check the transformed derivatives.
Raw named-joint partial arms would be a different, incompatible quantity.

PCA axes operationalize the experiment's anatomical long axes; the original
specimen landmarks, dimensions and posture are not reproduced exactly. Generic
model minus group-mean differences include these assumptions. Error bars are
between-specimen SD, not confidence intervals or model uncertainty. No geometry,
sign or scale is fitted to improve agreement. No accuracy threshold is used to
turn this comparison into validated human biomechanics. Other scenarios retain
their own evidence level and do not inherit this comparison.
