# Reproduce a calculation

The public route is a Linux x86-64 source checkout with Docker. See
[installation](GETTING_STARTED.md) first. A language model is not required.

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
python3 scripts/experiment.py --scenario pushup_flat_palm --output outputs/my-flat-palm
```

The current experiment uses external residual joint assistance, articulated
digits and a separately declared wrist derivative. Read the new
`manifest.json` before interpreting the result. The distributed palm-and-digit
criterion passed in the reference run. The full push-up, four-support,
stationary-support and numerical-bound checks failed. Choose a fresh output
directory. [Run receipt and media](demo/README.md)

## Evidence chain

The SDK exporter checks each size/SHA-256 before writing the success page.
`client.json` contains the run manifest; `manifest.json` is its standalone export.
A run includes:

- exact scenario version, normalized parameters, executable validation and hashes;
- engine/package versions, pinned model revision and model-asset digest;
- model derivation and control recipe, including external forces and work;
- `series.csv`, `summary.json`, saved `trajectory.npz` and state/coordinate order;
- chunked traces for all 700 actuators: excitation, activation, signed force,
  route length/velocity, mechanical power/work and sparse transmission Jacobian;
- contact/support data; detailed hands additionally include wrist and pectoral
  records, stationarity and palm-reference evidence.

`mjSTATE_INTEGRATION` is an opaque versioned engine vector. Read it with its
recorded state specification and MuJoCo version, using `allow_pickle=False`.
The authoritative reconstruction is the pinned source plus `model_recipe.json`;
diagnostic exported XML can round floats. Never treat a different model recipe
as an identical experiment because its model name matches.

## Repeat and negative controls

```sh
make test
make e2e
```

`make test` runs the full unit/contract suite, lint and wheel/sdist checks.
`make e2e` runs independent official-SDK clients over stdio and loopback HTTP,
including source discovery, numeric runs, artifacts, strict-input refusals and
native image transfer. `make test` writes compact packages under
`reports/packages/`. Run these checks in a separate checkout with an isolated
`COMPOSE_PROJECT_NAME` to preserve other runs and packages.

For regression work on the original `pushup` scenario, `make pushup-e2e`
independently repeats its states and checks restart, force, derivative and
perturbation behavior. Its `reports/V07_E2E.json` applies to that scenario.

For sweeps, finite-difference length-Jacobian discrepancy must be ≤1e-5 m/rad
at 1e-6 rad probes. Repeat tolerances are in each scenario's `validation.yaml`;
the push-up E2E consumes its configured absolute tolerance. These are numerical
regression tolerances in the recorded units, not human accuracy tolerances.
Bitwise repetition is tested on the release stack; no cross-platform or
cross-MuJoCo-version byte identity is promised. CPU rendering and physics have
separate checks; different rendering devices need not produce identical pixels.

The failed source knee interval and rejected legacy fist posture remain
regression fixtures. Their numerical constraints exposed an invalid assumption;
a past numeric PASS did not establish acceptable exercise technique. See
[hand methods](HAND_DETAIL.md) and `tests/fixtures/rejected_knuckle_pose.json`.

## Render the same states

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make render-build
make render-start
python3 scripts/visualize.py render --run-id <returned-run-uuid> --profile scientific --frames 23 --device cpu --wait --output outputs/my-render
```

Replace the placeholder with the run ID printed by the calculation, in the same
result store. Blender restores recorded states without integrating, and the
passport links every frame/time to its source hash. See
[render checks and clocks](RENDERING.md) and the [public demo](demo/README.md).

## Release acceptance and source packages

`python3 scripts/public_check.py` checks the public tree, relative links,
manifest-listed demo assets, package boundaries and private-data patterns
without network access. External references are checked separately, with access
errors recorded rather than silently treated as valid.

The [publication guide](PUBLICATION.md) explains verification of the exact
release tree. Historical demo passports preserve the scope of their own runs.

The wheel is code-only; it is not a stand-alone model database. The sdist
contains project data/configuration and text documentation, without downloaded
models, Blender binaries, videos, scenes or research archives. Exact apt package
versions are inventoried in `runtime-environment.json` but Debian repositories
are not snapshot-pinned. Preserve a verified image when exact OS dependencies
matter. [Public files and Release assets](PUBLICATION.md) are kept separate.

For claim-level Evidence Contract retrieval, the atlas lock, and private motion
comparison, see [Anatomical evidence](ANATOMICAL_EVIDENCE.md).
