# Repository agent rules

## Safety and existing evidence

- Git state/history are read-only unless the current task explicitly authorizes a Git mutation.
- Local implementation and checks within the requested scope are allowed. No sudo, system/driver changes, or control of unrelated processes.
- Mark an unsafe hardware operation or an operation needing unavailable confirmation BLOCKED and continue independent work.
- Preserve original run states, forces, manifests and hashes. Record a later rejection separately; do not rewrite historical results to conceal an error.

## Human movement: references before implementation

Before choosing or changing an exercise posture, trajectory, support placement or joint orientation:

1. Search the internet for the **named exercise variant performed by real people**. Find at least two relevant visual references, preferably a study with participant photographs plus a professional exercise demonstration. Use side/front views and inspect the start, bottom and return phases where available.
2. **Open and visually inspect the actual images/video frames.** Search snippets, image captions, text descriptions, AI-generated images and an agent's recollection are insufficient. If a view or phase is unavailable, record that gap.
3. Record source URLs, access date, the viewed figures/frames, variant name and concrete observations in the scenario references before implementing its motion. Distinguish observations from inferred 3D geometry, chosen numerical targets and experimental measurements. Keep downloaded review copies under ignored outputs unless redistribution is licensed.
4. Compare the chosen human references with the model's anatomy, joint ranges and degrees of freedom. Do not silently substitute an easier exotic variant to make IK, dynamics or rendering pass. Do not widen anatomical ranges or retune muscle strengths just to obtain attractive motion. A model change needs explicit source evidence, separate provenance and a clear explanation.
5. Define acceptance for the actual technique: hand/fist direction, hand position relative to head/shoulders, elbow path, depth, body alignment and stationary supports. A numerical cycle or successful render alone cannot establish a plausible exercise.
   For the current flat-palm push-up, the user specifies palms at shoulder/chest level. Use the actual palm supports and shoulder/chest floor projections; the head is not a placement target. Keep palm, wrist and fingertip landmarks distinct.
6. If the references and current model are incompatible, preserve a reproducible negative experiment and state the model limitation. Continue independent implementation and measurements; do not label a different movement as the requested exercise.
7. Before handoff, inspect matched start/bottom/end simulation frames beside the chosen human references. Record remaining discrepancies. Experimental human validation requires more than visual similarity.
8. A requested visible pose correction must replace the main viewer's motion with newly computed states. Changing a caption or acceptance gate while replaying the old pose is insufficient. Keep the rejected old motion only in a clearly separate archive.

## Muscle measurements

- Save actual excitation, activation, native transmission forces, lengths/velocities and mechanical work for the available actuators. Recompute them after a trajectory change.
- For push-ups, explicitly inspect and report bilateral pectoral paths and their phase-dependent forces/activation, alongside triceps and stabilizers. Record the source identifiers and aggregation definitions.
- Display measured model activation; never manufacture chest activation or change colors to match an expected conclusion. Paths are not anatomical muscle volumes, source joint limits are not clinical norms, and model activation is not normalized surface EMG.
- Run existing relevant tests and real saved-state/render checks. Report both passing checks and remaining model/reference mismatches.

## Public source publication gate

Before recommending a **freshly exported** public source tree, run
`python3 scripts/public_check.py --strict-tree` inside that export. Do not
substitute checks on a private working tree. Preserve prior scientific demo
passports and historical RC reports without relabeling them as new E2E evidence.
If the target machine cannot run Docker/MuJoCo, leave those tests BLOCKED.
