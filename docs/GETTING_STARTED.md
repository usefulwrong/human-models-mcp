# Getting started

Tested platform: Linux x86-64 with Docker Engine and Compose v2. The scientific
container runs pinned Python 3.12; host Python 3.13 is used for launchers and the
SDK client in the RC check. macOS, Windows, ARM and non-Docker installs have
not been release-tested.

## Requirements

- Docker Engine with Compose, accessible to your local account.
- GNU Make and Python 3.12 or 3.13 with `venv` and pip.
- Internet during the first build: PyPI, Debian, GitHub raw assets and the
  official Blender download server. Both runtimes then have networking disabled.
- Science: 2 CPU cores / 3 GiB RAM. Renderer: 4 cores / 8 GiB. Allow at least
  12 GiB available RAM for both and 15 GB disk for images, downloads and a few
  runs. Long research archives need more space.

Extract the repository into a directory owned by your user. Run commands from
its root, without root privileges. Export `HMM_UID`/`HMM_GID` as below once per
shell so both containers use your account IDs. Make also sets these defaults
for its own commands. This avoids changing ownership or making result folders
world-writable. The generated MCP connector includes the selected user IDs.

## First calculation

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
python3 scripts/experiment.py --scenario pushup --output outputs/my-pushup
```

`make build` verifies every model file against `models.lock.json`, creates
`.client-venv` with hash-locked packages and builds the CPU runtime. The launcher
runs an independent MCP SDK client and exports checked CSV/JSON/NPZ files plus
`client.json`, `manifest.json` and `index.html` to the new directory. No API key,
language model or Blender is needed.

The separate assisted palm calculation is:

```sh
python3 scripts/experiment.py --scenario pushup_palms --output outputs/my-palms
```

A scenario's `render` flag requests native diagnostic images. Blender renders
are separate operations on saved states.

## First Blender preview

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make render-build
make render-preview
```

This downloads and checks official Blender, computes a fresh `pushup_palms`
result, starts a project renderer and renders five states on CPU. Open the
printed local HTML path. A first image build can take several minutes.
No GUI or NVIDIA hardware is required. See [Rendering](RENDERING.md) to render
more frames from the same saved result.

## MCP connection

```sh
python3 scripts/print_client_config.py
make client
```

The generator prints a TOML connector for this checkout without editing agent
configuration. `make client` exercises an elbow sweep with the official SDK.
Use the printed Docker command for stdio; Make itself writes command text to
stdout and must not be the protocol connector. [Tool guide](MCP_API.md).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Docker connection denied | Check your Docker installation and account access. Never expose its socket to MCP. |
| `venv` or pip missing | Install your distribution's venv support, then retry. |
| Cannot write results or queue | Export the host UID/GID as above; check ownership of your project result directories. |
| Download/hash failure | Check connectivity and retry provisioning. Never disable verification. |
| Output directory exists | Choose a new name; existing evidence is retained. |
| Run/job quota reached | Export existing evidence, then choose a fresh result store or queue. There is no automatic deletion. |
| Render stays queued | Start `make render-start`, with the same scientific store as the submitting runtime. |
| GPU unavailable | Select `--device cpu`; NVIDIA is optional. |

`HMM_RESULTS_DIR` selects an owner-controlled scientific store, not a remote
MCP input. Use an absolute directory inside this checkout and provide it to both
runtime/client and renderer. `render_jobs/` is a separate queue.

## Offline use and packaging

After building, normal calculations and renders need no network. A new machine
needs the downloads again. This is a source-checkout preview, not a self-contained
PyPI install: the wheel contains code and the frozen palm reference; scenarios,
locks and provisioned models are project data. Run from the project root.
Docker explicitly sets `HUMAN_MODELS_HOME=/app`.

Stop this project's renderer with `docker compose stop renderer`. No cleanup is
part of the quick start. Preserve manifests/data before removing your own
outputs. Do not prune shared Docker images or volumes for troubleshooting.

[Reproducibility](REPRODUCIBILITY.md) · [Security](SECURITY.md)

The optional BodyParts3D cache and Fit3D comparison use separate operator
workflows. [Atlas and reference setup](V08_ANATOMICAL_EVIDENCE.md)
