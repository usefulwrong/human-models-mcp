# Human Models MCP

**An AI agent can describe a movement. Can it check that movement against a physical model?**

Human Models MCP connects AI agents to **computational musculoskeletal models**. An agent can select an experiment, run MuJoCo, inspect joint motion, contacts and muscle-actuator data, and ask Blender to render the *saved simulation states*. The same tools work from a CLI without an LLM.

**UsefulWrong · v0.8.0 Research Preview · Anatomical Grounding & Evidence** · [MIT wrapper](LICENSE) · [Source and model licenses](notices/THIRD_PARTY.md) · [CPU checks](https://github.com/usefulwrong/human-models-mcp/actions/workflows/ci.yml)

[![Computed palm push-up: scientific animation, not measured human motion](docs/demo/animation.gif)](docs/demo/animation.mp4)

**Watch the [MP4](docs/demo/animation.mp4) · Examine the [experiment, raw data and scientific passport](docs/demo/README.md).**

This is a computed **palm push-up with muscle-actuator recruitment *and external joint assistance***. It is not the separate muscle-controlled `pushup` experiment. The highlighted lines are muscle/tendon **transmission paths**, not deforming anatomical muscle volumes; their color represents model activation. The movement is not a clinically validated exercise demonstration.

The v0.8 release includes the optional pectoralis render recipe and a separate
experimental moving atlas with full-resolution arm surfaces. The whole-body
anatomical acceptance gate remains **PARTIAL**. [Moving atlas coverage and checks](docs/V08_MOVING_ATLAS.md)

## Why this exists

An LLM can propose a plausible-looking pose without checking whether a particular body model can assume it, what contacts are required, or what forces its actuators produce. Human Models MCP gives the agent something outside its text predictions to interrogate.

For example, an agent can ask the system to perform a push-up, inspect the simulated elbow and wrist trajectories, retrieve actuator activation and transmission forces, and render the result. The answer comes with the model version, control assumptions, numerical checks and artifacts. A **numerically successful run is not automatically a valid human movement**: the scenario exposes its own acceptance checks, which may fail.

This is an **open research and agent-tooling experiment**, useful for investigating model-based reasoning, repeatable musculoskeletal computations and scientific visualization. It is **not** a medical, injury-prediction, ergonomics-certification or human-safety product.

## What works today

| Area | Available now | Boundary of the claim |
| --- | --- | --- |
| Agent tools | 14 MCP tools for discovering models/scenarios, running experiments, searching attributed local sources and retrieving evidence | Local single-user service; no hosted clinical API |
| Simulation | MuJoCo **3.17.0** with pinned **MS-Human-700** assets; kinematic, dynamic and contact experiments | Derived model geometries, idealized contacts and declared controls |
| Muscles | Actuator excitation/activation, transmission-force and related numerical traces where available | 700 **actuators** are not 700 complete deformable anatomical muscles; activation is not EMG |
| Scientific visualization | Saved-state export to Blender; PNG/GIF/MP4, frame mapping, plots and provenance | A render does not add or validate new physics |
| Reproduction | Docker/Compose, locked dependencies, model hashes, Python clients, CLI and scenario folders | Release-tested on **Linux x86-64**; GPU optional, CPU path supported |

**Not implemented:** personalized human bodies, complete internal organs, volumetric muscle deformation, garment fit, validated ergonomic reach/risk assessments, injury prediction, or automatic verification that a designed object is safe for a person. CAD, games, animation and safety-related research are *possible future integrations*, not features of this release.

### The computational path

```text
Agent / MCP client     or     CLI / Python client
                 │
        choose model + scenario
                 │
        MuJoCo scientific calculation
           │                  │
    joint/force data       saved states
           │                  │
     manifests + CSV    Blender (optional)
           │                  │
           └─────────┬────────┘
             inspectable evidence
```

The scientific calculation is CPU-based; Blender can render on CPU or use an available NVIDIA backend. The renderer does not recompute the physical movement.

## Try it locally

**Requirements:** Linux x86-64, Docker Engine + Compose v2, GNU Make, Python 3.12/3.13 with `venv` and pip. Allow approximately **12 GiB RAM** and **15 GB free disk** for combined science/render work. Internet is needed for the initial verified model and dependency downloads; no GPU, LLM account or desktop Blender installation is required. [Detailed prerequisites](docs/GETTING_STARTED.md).

**A — Compute an experiment and inspect its numerical results:**

```bash
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
python3 scripts/experiment.py --scenario pushup --output outputs/my-pushup
```

Open the reported local `index.html` in `outputs/my-pushup/`. The exporter saves checked results and their provenance; choose a **new output directory** for subsequent runs. This is the original `pushup` scenario, distinct from the assisted palm demo above.

**B — Generate a Blender preview:**

```bash
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make render-build
make render-preview
```

The preview computes `pushup_palms`, renders five selected states on **CPU**, and prints the location of a local HTML viewer with media and evidence. The README animation is a separate, longer precomputed example. [Rendering and full-frame exports](docs/RENDERING.md).

The first build downloads several GB of pinned dependencies/models. Model hashes are checked; do not disable verification to bypass a download failure. [Troubleshooting](docs/GETTING_STARTED.md#troubleshooting).

Optional [anatomical replay and evidence](docs/V08_ANATOMICAL_EVIDENCE.md)
adds a pinned BodyParts3D right clavicular pectoralis surface to a saved push-up,
with registration residuals and a separately licensed asset cache. A local
Fit3D importer can compare geometric motion if the operator supplies a licensed
recording. See the [v0.8 acceptance report](reports/V08_SCIENCE.md).

## Connect an AI agent

After `make build`, generate the local **Codex-style MCP stdio configuration** for your checkout:

```bash
python3 scripts/print_client_config.py
make client
```

The first command **prints** TOML; it does not edit your agent configuration. Copy the generated connector into the appropriate client configuration and restart that client. The second command tests a real MCP connection without an LLM. Do not use `make stdio` as the protocol command: its build-system output can corrupt stdio. See [MCP clients, schemas and example calls](docs/MCP_API.md).

An agent can now follow this workflow:

1. `list_models` / `list_scenarios` — see the models and experiments actually available.
2. `describe_scenario` — inspect accepted parameters and scientific limitations.
3. `run_scenario` → `get_result` — calculate and inspect numerical acceptance, **not just execution status**.
4. `get_artifact` — retrieve checked scientific data; optionally `render_result` → `get_render_job` → `get_render_artifact` to create and download Blender media.

There is no arbitrary Python/script execution via MCP. The server is intended for **local, trusted research use**. Do not expose its HTTP test transport to the internet. [Security model](docs/SECURITY.md).

## Three push-up modes are not interchangeable

| Scenario | What is calculated | Important limitation |
| --- | --- | --- |
| [`pushup`](scenarios/pushup/README.md) | Native muscle-actuator control, no external joint/body force in `muscle` mode | Synthetic target, simplified pads/damping; check the exercise/contact gates |
| [`pushup_palms`](scenarios/pushup_palms/README.md) | Palm contacts and muscle recruitment **with additional residual joint assistance**; shown in the video | Fixed horizontal support guides, modified model wrist bounds; **not muscle-only** |
| [`pushup_knuckles`](scenarios/pushup_knuckles/README.md) | Neutral-fist variant with muscle recruitment **and additional joint assistance** | Rigid finger pose and simplified hand/floor physics |

A model can return `computed` while some exercise or contact criteria fail. Read the scientific acceptance fields and the [exact demonstration conditions](docs/demo/README.md) before citing a result. Simulation findings are **not human measurements**, and neither fitted geometry nor the published wrist moment-arm comparison establishes safety or clinical validity.

## Documentation and participation

| Need | Read |
| --- | --- |
| Install and resolve first-run problems | [Getting started](docs/GETTING_STARTED.md) |
| Use MCP tools or programmatic clients | [MCP and CLI](docs/MCP_API.md) |
| Understand the architecture and source models | [Architecture](docs/ARCHITECTURE.md) · [Models](docs/MODELS.md) |
| Reproduce, cite or criticize an experiment | [Reproducibility](docs/REPRODUCIBILITY.md) · [Scientific scope](docs/SCIENTIFIC_SCOPE.md) · [Citation](CITATION.cff) |
| Understand the media and its underlying data | [Public demo](docs/demo/README.md) · [Rendering](docs/RENDERING.md) |
| Propose a fix or a research use case | [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/usefulwrong/human-models-mcp/issues) |
| Release, licensing and security | [Changelog](CHANGELOG.md) · [v0.8.0 release handoff](docs/RELEASE_080.md) · [Notices](notices/THIRD_PARTY.md) · [Security](SECURITY.md) |

**Built by [UsefulWrong](https://github.com/usefulwrong).** Contributions are welcome, especially reproducible failures, independent benchmarks, model-boundary findings and improvements to agent usability. Please keep reported model behavior distinct from conclusions about real people.
