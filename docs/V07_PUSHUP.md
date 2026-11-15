# Original primary-model push-up methods

This document describes `pushup` 1.0.0. The separately assisted detailed-hand
variants are described in [hand methods](HAND_DETAIL.md); their muscle-only
status is not inherited from this scenario.

The primary MS-Human-700 has 85 scalar coordinates, 700 muscle actuators and 42
internal joint equalities. Locomotion has only 100 lower-body actuators and is
not used. Pectoralis, triceps, deltoid, serratus, abdominal and spinal paths are
present. Scapular coordinates are equality-coupled to shoulder elevation; their
anatomical presence does not imply independent scapular control. Compiled inventory
is available through `get_joint_info` and each run manifest.

The model derivation adds a floor and four massless spherical mechanical contact
pads. Source self-contact is retained. Separate collision masks restrict floor
contacts to these pads; other body-floor collision is incomplete. Palm pads are
not anatomical tissue, flat palms or pressure distributions. Internal damping
is at least 10 N*m*s/rad for hinge DOFs and 10 N*s/m for slides, with no added root
damping. Source forces, mass, inertias, ranges and internal equalities remain.
The two supported timesteps are 1 ms and 0.5 ms, using implicitfast integration.
Nominal pad/floor friction is 1.3 and solref is [0.01, 1] on both surfaces. These
are declared experimental mechanical assumptions, not identified human values.

A deterministic bounded IK generates 17 reference poses from 0.2 to 1.8 rad elbow
flexion, keeping target hand/toe points fixed. Only initialization assigns a pose
to the physical model. During the 2.4 s experiment all later states result from
`mj_step`: 0.2 s settling, 2 s descent/ascent and 0.2 s final hold. The root has no
actuator, weld or body wrench. Internal viscous damping dissipates energy and
must be considered when interpreting the effort; this is a research mechanical
model, not an identified human controller.

The default feedback loop runs at 100 Hz. A proportional target torque is formed
on independent internal coordinates, clipped to 200 N m. Source equality tangent
rows map muscle transmissions into those coordinates. Native passive force and
active force gain at current length/velocity form a bounded activation allocation
problem, solved by 300 projected accelerated-gradient iterations with ridge
1e-5 and row scaling. The allocation is sent as excitation; native activation
dynamics, force-length and force-velocity behavior then evolve in MuJoCo. Actual
activation is never replaced with the optimization result during integration.
Temporary zero/one activation evaluations calculate force coefficients and restore
the actual state before integration. `qfrc_applied` and `xfrc_applied` are exactly
zero in muscle mode. The external comparison applies only internal generalized
joint torques and has zero muscle excitations.

All 700 actuators have excitation, activation, signed transmission force, length,
velocity, power and sparse dL/dq rows saved every 20 ms in bounded NPZ chunks.
For actuator i, generalized force is J_i*F_i and mechanical power is F_i*Ldot_i.
Summing contributions is checked against native qfrc_actuator. Numerical checks
also use independent COM acceleration/angular-momentum maps, decoded contact
frames, friction cones, engine warnings, activation bounds, soft joint-limit
violations and independent path finite differences. Repeats and a half timestep
are separate experiments, not inferred from one run.

`computed` is execution status. Exercise acceptance separately checks chest
excursion, bilateral elbow flexion/return, timing of the bottom point, plank joint
deviation, continuous four-support loading after settling, support displacement,
penetration and numerical residuals. Thresholds are exported in summary.json.
The 6 cm support-displacement bound permits measurable movement and is not a
claim of fixed palms/toes or experimentally stable human technique. Human
experimental validation and external volumetric anatomy remain separate statuses.

Use the public toolkit without an AI agent:

```sh
make build
make pushup-e2e
mkdir -p reports/v07-cli-science
HMM_RESULTS_DIR="$PWD/reports/v07-cli-science" python3 scripts/experiment.py \
  --scenario pushup --output outputs/pushup-numbers
```

The last command uses a fresh official MCP SDK client and downloads every
scientific artifact with hash verification. A separate store avoids the retained
main store's 200-run quota. Existing results are never automatically deleted.
For Blender:

```sh
make render-build
mkdir -p reports/v07-cli-science
HMM_RESULTS_DIR="$PWD/reports/v07-cli-science" docker compose -p human-models-mcp-night up -d --no-deps renderer
HMM_RESULTS_DIR="$PWD/reports/v07-cli-science" .client-venv/bin/python examples/mcp-client/render_client.py \
  --scenario pushup --profile scientific --frames 61 --fps 25 --width 960 --height 540 \
  --samples 8 --device cpu --output outputs/pushup-media
```

Use a new output directory for each run. `render_client.py` discovers capabilities,
computes a new physical experiment, requests Blender, downloads PNG/MP4/GIF,
source.zip, scene.blend and metadata through public MCP chunks, and checks hashes.
The host starts Docker; neither runtime has network access or controls Docker.
Alternatively call the Python `run_scenario`, `render_result`, `get_render_job`
and artifact functions, or render an existing run with `scripts/visualize.py`.
The same store override must be supplied to that launcher and the renderer.

The `.blend` contains named layer collections. The [public demo](demo/README.md) is the assisted palm variant. Additional
layer choices can be rendered from identical saved physical states. Native
geometry and tendon paths are measured source structures; line thickness,
lighting, colors, graph layout and camera are presentation parameters. Graphs
show actual model group means. No fabricated activation or volume geometry is
introduced.
