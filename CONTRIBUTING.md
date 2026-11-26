# Contributing to Human Models MCP

Human Models MCP is a **research preview**: a local interface between AI agents, scientific musculoskeletal computation and saved-state visualization. Scientific criticism is as valuable as code. A failed experiment with a reproducible counterexample can be a useful contribution.

**Start here:** [README](README.md) · [Getting started](docs/GETTING_STARTED.md) · [Scientific scope](docs/SCIENTIFIC_SCOPE.md) · [Architecture](docs/ARCHITECTURE.md) · [Movement methods](docs/MOVEMENT_METHODS.md).

## What we are looking for

| Contribution | Preferred first step |
| --- | --- |
| Installation or MCP bug | Open a bug report with commands, versions and sanitized logs |
| Physical/model discrepancy | Open a **scientific issue** with the scenario, quantity, units and supporting evidence |
| Missing or misleading documentation | Focused pull request, including corrected commands or model limitations |
| Reproducibility/benchmark failure | Issue with raw inputs, independent reference, comparison method and repeatability |
| New engine, anatomical source, scenario or major control change | **Discuss first** in an issue; specify provenance, scientific question, resources, licenses and tests |
| Security problem or data exposure | Follow [private security reporting](SECURITY.md); do not post exploit details in public issues |

The **0.8.0 release is in feature freeze**. Release changes address confirmed defects, installation, reproducibility, documentation and security. Propose larger research additions for a future iteration.

## Before filing an issue

1. Check [existing issues](https://github.com/usefulwrong/human-models-mcp/issues) and the [scientific limitations](docs/SCIENTIFIC_SCOPE.md).
2. Identify the exact **wrapper version**, model variant, scenario ID/version, control mode, engine version and, when relevant, render profile. The scientific passport and manifest contain these values.
3. Distinguish an execution error, a numerical failure, an experiment acceptance failure and a problem of human interpretation. An MCP result of `computed` **does not imply** an accepted movement.
4. Supply the smallest reproducible input. Use the public issue forms (`Bug report` or `Scientific issue`) and include *expected vs. actual* observations with units and tolerances, plus the exact commands used.
5. Remove access tokens, private paths, patient images, private scans, personal data and unrelated logs. Reproductions should use permitted non-sensitive data.

For scientific disagreements, state the **source** of each assertion. An equation, paper, measurement, anatomical convention or photograph is useful when it matches the model's pose, definitions and coordinate frame. Visual plausibility alone is not validation.

## Development environment

The release-tested development target is **Linux x86-64** with Docker Engine, Docker Compose v2, GNU Make and Python 3.12/3.13 + `venv`/pip on the host. The science container runs pinned **Python 3.12**. GPU is optional. A complete science + CPU-render environment requires roughly **12 GiB RAM** and **15 GB free disk**; the first build downloads verified external assets.

From a clean checkout:

```bash
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
make test
make e2e
make pushup-e2e
```

`make build` provisions locked models and dependencies, creates a local client virtual environment and builds the CPU runtime. Tests run in the scientific Docker container. For quick independent client calls, use [MCP and CLI](docs/MCP_API.md). No cloud LLM or GPU is needed for the CPU suite.

Do **not** run the container with `--privileged`, mount `/var/run/docker.sock` inside it, or make the local MCP HTTP transport public. The Docker daemon on the **host** remains privileged infrastructure; use a trusted test machine. See [security boundaries](docs/SECURITY.md).

### Test the route your change affects

| Scope | Minimum relevant checks |
| --- | --- |
| Documentation, distribution, demo | `python3 scripts/public_check.py` and a review of all changed commands/links; `make test` if installed dependencies or package declarations changed |
| MCP/tool or scenario contract | `make test`, `make e2e` and an independent [SDK client call](docs/MCP_API.md) |
| Muscle, contact or controller math | `make test`, `make pushup-e2e`, source-specific numerical/invariant tests and a fresh simulation with the acceptance fields inspected |
| Blender/export/visual layers | `make render-build`, `make render-e2e`, saved-state / geometry verification, real media decode and inspection of start/bottom/end frames |
| GPU behavior | `make render-gpu-smoke` on a host with a working NVIDIA container runtime **plus** CPU fallback; never label an unavailable GPU check PASS |
| Public-source archive | `python3 scripts/public_check.py --strict-tree` **inside a fresh, clean public export**, not an ordinary working tree with results |

See [render methodology](docs/RENDERING.md) and [reproducibility](docs/REPRODUCIBILITY.md) for outputs and limits. GitHub's CPU workflow checks a bounded subset; a green CI badge **does not** prove GPU behavior, clinical correctness or all media workflows.

Do not add `skip`, `xfail`, weaker numerical thresholds or rewritten expected data merely to make a failing test green. Record `PASS`, `FAIL`, `BLOCKED` or `NOT_RUN` for relevant checks. If an independent dependency is unavailable, say so explicitly.

### Reproduce a published experiment

```bash
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
python3 scripts/experiment.py --scenario pushup_flat_palm --output outputs/reproduction-01
```

Choose a new directory every time: existing runs and failed experiments are evidence, not disposable scratch data. Retain `manifest.json`, scientific acceptance, numerical CSV/NPZ and the model recipe. If changing a scenario, run before/after comparisons from **separate outputs** and report the model hash, inputs, units and tolerances. Do not modify historical manifests or force a new result to match a visually pleasing target.

The [articulated contact demo](docs/demo/README.md) uses external joint assistance. Identify contacts, controller, wrist settings and acceptance criteria when comparing it with the muscle-controlled `pushup` scenario.

## Scientific standards

Changes to exercise pose, muscle modeling, joint bounds, contact surfaces or controls need more than a passing render.

- Follow the [movement and measurement methods](docs/MOVEMENT_METHODS.md) when changing scientific behavior.
- Specify the anatomical reference, mechanical assumptions and coordinate systems. Inspect actual human pose references when relevant; do not substitute a visually convenient pose or an AI-generated anatomy diagram.
- Preserve separate labels for geometry, kinematics, forward dynamics, muscular control, externally assisted control, measured data and clinical evidence. These are different claims.
- Where possible, test against **independent measurements** with aligned signs/units/frames and a stated comparison metric. One wrist benchmark does not validate full-body push-ups.
- Keep negative controls and rejected experiments. A failing result should remain inspectable rather than being hidden by a changed acceptance gate.
- When displaying muscle paths, disclose that they are **transmission paths**, not volumetric deformable anatomy. Derived color is model activation, **not surface EMG**.
- Provide provenance (URL/DOI, source revision, asset hash), redistribution rights and required attribution for any new model, image, video or dataset. **Do not submit identifiable patient images.**

When a scientific claim cannot be verified from the available data, preserve it as a hypothesis or a limitation instead of making the README sound more certain.

## Code and architectural changes

Work in a feature branch of your fork and submit a **focused PR**. Include an issue link when one exists, an explanation of the behavior being changed, a test reproducing the failure where practical, and the post-change evidence. Smaller PRs are easier to review.

- Follow existing module boundaries: MCP/API, model adapters, scenario definitions, scientific data, rendering and clients. Prefer reusing these contracts rather than adding a new framework.
- Use the project's existing Python style (`ruff` configuration in [`pyproject.toml`](pyproject.toml)); preserve scientific variable names and explicit physical units.
- Keep schema changes backward-compatible unless a larger versioned design has been agreed. Update affected client examples, tests, skills, docs and manifests together.
- Do not hard-code a local path, author account, specific run UUID or machine-specific GPU setup.
- New dependencies must have a concrete purpose, checked versions and compatible distribution terms. Avoid expanding the public artifact with downloaded models or Blender binaries.
- A scientific asset or benchmark needs a provenance/rights note and appropriate separation from project-owned MIT code. See [third-party notices](notices/THIRD_PARTY.md) and [citation](CITATION.cff).

### Pull-request checklist

Before requesting review, confirm that the PR describes:

- [ ] What was wrong or missing; exact reproducer and user/researcher impact.
- [ ] What changed, including scientific assumptions and outward-facing behavior.
- [ ] Relevant tests and E2E with commands, observed results and any `BLOCKED` or `NOT_RUN` checks.
- [ ] Compatibility, limitations, units, source/model versions and citations where applicable.
- [ ] Documentation, CLI/MCP tool examples and demo/passport updates if necessary.
- [ ] License and privacy checks; no secrets, identifiable patient data or unrelated output archives.

AI-assisted contributions are welcome **when the contributor understands and verifies the work**. Please disclose substantial AI generation or editing in the PR description and distinguish generated suggestions from independently checked calculations, images and citations. The person submitting the PR is responsible for evidence and license compliance.

## Review and release decisions

Maintainers may request a minimal reproducible test, a smaller scope or stronger independent scientific evidence before merging. A model enhancement with uncertain validation can be valuable as an explicitly experimental adapter, but it must not silently replace the current validated-by-tests computation path.

Public release packaging is performed by maintainers. Ordinary contributors need not prepare release tags, large GitHub assets or issue a DOI. The [publication procedure](docs/PUBLICATION.md) describes the separate checks used for public-source trees. Security reports follow [SECURITY.md](SECURITY.md), not the public issue tracker.

**UsefulWrong values counterexamples.** A result that reveals a limitation of the model is better than an attractive render that hides it.
