# Human Models MCP on Windows

This unsigned 0.9.1rc1 release candidate targets Windows 11 x64. The normal
setup uses a project-local Python 3.12 runtime. It needs no administrator
account, Docker Desktop, WSL, Git or developer tools.

## First experiment

1. Verify the ZIP against the release `SHA256SUMS` and extract it to a writable
   folder using Windows Explorer.
2. Open `Start.cmd` and approve the Core installation. The launcher displays
   download and disk estimates and records progress in `.runtime/install.log`.
3. Select **Run first experiment** for the CPU elbow sweep. The menu also
   opens the results folder and lists the other scenarios.

Core runs can skip diagnostic graphics. To request a diagnostic image, run
`Doctor.cmd`. A working GLFW context is required for MuJoCo images. A
failed image request is reported in the run manifest. The Blender renderer
uses CPU Cycles and its own worker.

## Automation

Run these commands from the extracted folder using Command Prompt. Absolute
launcher paths also work from elsewhere.

```bat
Install.cmd --yes core
Start.cmd run elbow_sweep --output outputs\first-elbow
Start.cmd config --format toml
Start.cmd config --format json
Start.cmd config --mode anatomy
Start.cmd config --mode docker
Start.cmd start-service http
Stop.cmd
```

The native MCP configuration names the portable Python executable and sets
the checkout directory. Copy the generated configuration into your MCP
client. The stdio server can run independently of the launcher. HTTP listens
at `http://127.0.0.1:8765/mcp`.

## Optional components

```bat
Install.cmd explorer
Install.cmd renderer
Install.cmd development
Start.cmd start-service explorer
Start.cmd start-service renderer
Start.cmd render RUN-UUID --output outputs\preview
```

The Explorer listens at `http://127.0.0.1:8766/`. Review the BodyParts3D source
terms before installing. Local operator copies keep the existing license and
access conditions. [Anatomy Explorer and saved motion](docs/V09_ANATOMY_LAB.md)

Blender renders the original recorded states. `RUN-UUID` identifies a
compatible saved scientific run, such as `elbow_tracking`. Rendering,
retrieval and the independently recorded scientific status are available
through MCP. [Render workflow](docs/RENDERING.md)

## Offline cache and relocation

On an online Windows machine, run
`Install.cmd --yes --prepare --cache D:\hmm-cache core renderer`.
Add `explorer` only if you are permitted to transfer the resulting source
cache. Keep the ZIP and cache together for local transfer. On the target,
set `HMM_OFFLINE_CACHE` to the local cache folder before running
`Install.cmd --yes core renderer`. The installer verifies locked archives,
wheels and model inputs before use. Licensed anatomy inputs remain
operator-local.

Keep the `results`, `render_jobs` and `outputs` folders and any source cache.
Extract the new source to another directory, then reinstall components from
the preserved cache and regenerate MCP configuration for the new location.
Use `Doctor.cmd` to detect damaged components and `Install.cmd --yes --repair
core` to repair Core using the locked downloads. See the installation log
for missing files and source-specific errors.

## Docker Desktop alternative

With Docker Desktop configured for Linux containers, provision the locked
models using Core and build from the extracted directory.

```bat
Install.cmd --yes core
docker compose build runtime
Start.cmd config --mode docker
```

An existing Linux offline image can also be used with Docker Desktop. Native
execution inherits the user's filesystem and network access.
[Security boundaries](docs/SECURITY.md)
