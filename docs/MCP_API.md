# MCP and CLI

The core runtime exposes 15 tools through the official MCP SDK. `list_tools` is the
authority for exact JSON schemas; `describe_scenario.parameter_schema` provides
bounded scientific inputs. No model path, shell, Python or remote download can
be supplied as a scientific parameter.

| Tools | Purpose |
| --- | --- |
| `list_models`, `describe_model`, `get_model_capabilities`, `get_joint_info` | Availability, provenance, measured inventory and scope |
| `list_scenarios`, `describe_scenario` | Discover folders, parameters and executable validation |
| `search_sources` | Offline attributed source/identifier lookup, not a computed result |
| `run_scenario`, `get_result`, `get_artifact` | Compute, inspect status and retrieve manifest-listed scientific bytes |
| `get_contact` | Read verified saved contact forces and moments for a part at a selected state |
| `list_render_profiles`, `render_result`, `get_render_job`, `get_render_artifact` | Render existing states, poll and retrieve media chunks |

## Stdio

After `make build`, run:

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
python3 scripts/print_client_config.py
make client
```

Copy the generated TOML into a compatible MCP client's configuration. Paths
are resolved for the current checkout. No author-specific configuration file
is shipped. The Docker connector uses `-T`, not a TTY; stdout carries MCP.
The generator does not modify the user's agent configuration.

The generic SDK bridge can inspect live schemas and call a tool without AI:

```sh
.client-venv/bin/python examples/mcp-client/call_tool.py discover --trace-dir outputs/my-requests
.client-venv/bin/python examples/mcp-client/call_tool.py list_scenarios --trace-dir outputs/my-requests
.client-venv/bin/python examples/mcp-client/call_tool.py run_scenario --arguments '{"scenario_id":"pushup_flat_palm","parameters":{"render":false}}' --trace-dir outputs/my-requests
```

The receipt prints the run ID. Pass it to `get_result`, then retrieve each
manifest artifact with `get_artifact`. The complete exporter handles this for
scientific runs:

```sh
python3 scripts/experiment.py --scenario pushup_flat_palm --output outputs/my-flat-palm
```

Idempotency keys return the same persisted result for the same normalized
request; changing parameters under a key is rejected. Omit a key for a new
independent repeat. `computed` does not mean every exercise gate passed:
inspect `scientific.acceptance` and `scientific.checks`.

For claim-level evidence, call `get_result(run_id, claim_id="metric:<name>")`
or `get_result(run_id, claim_id="artifact:<id>")`. Use `claim_id="all"`
to enumerate claims. [Evidence fields and interpretation](ANATOMICAL_EVIDENCE.md#evidence-contract-10)

Use `get_contact(run_id, part="hand_r", sample=55)` to inspect the
right-hand contact receipt at an exact saved state. [Exact-state walkthrough](PREVIEW_WORKFLOW.md)

## Anatomy Lab

The optional `anatomy_lab` tool extends the core server with source anatomy
search, relationships, scenes, saved motion and native muscle queries. Run
`lab_mcp` with a provisioned catalog to use it over MCP. The Explorer's
`POST /api/query` accepts the same typed request as a plain HTTP JSON body.
[Setup and copy-paste examples](V09_ANATOMY_LAB.md#query-anatomy_lab)

## Media and HTTP

[Discover the bounded recipes](ANATOMICAL_EVIDENCE.md#render-an-anatomical-layer-from-saved-states)
through `list_render_profiles`, then pass `recipe` to `render_result`.
Identical recipes may reuse an active or completed job for the same code,
renderer locks and source manifest. A worker rejects a newly queued recipe
if its code or locks differ from the submission.

[Rendering](RENDERING.md) describes the SDK/CLI render client. Render jobs move
through `queued`, `running`, `completed` or `failed`. A completed render does
not change the source scientific result. `get_render_artifact` returns at most
262144 bytes per call, with chunk/full SHA-256, total size, contiguous offsets
and EOF. The SDK downloader verifies the reassembled file; do not put a whole
video in a model's context. Scientific `get_artifact` keeps a 2 MiB/file cap.

HTTP is a loopback-only test/embedding transport. Inside one runtime container,
start `python -m human_models_mcp --transport http`, then use the SDK at
`http://127.0.0.1:8765/mcp` in the same namespace. `make e2e` performs this with
fresh clients and rejects browser Origins. That URL is not reachable from a
host client because Compose publishes no ports. The optional Explorer's
typed HTTP endpoint has its own private-subnet mode. [Viewer setup](V09_ANATOMY_LAB.md#open-the-viewer)

## Expected refusals

- Unknown scenario: `unsupported`.
- Unrecognized parameters, coercions, nonfinite values: `invalid_input`.
- Traversal in a run/artifact ID: `invalid_input`.
- `get_model_capabilities(model_id="ms_human_700", quantity="medical_safety")`:
  `unsupported`, without a fabricated medical metric.
- Dynamic skin, organ function, muscle volume mechanics and wrist ligament loads:
  unsupported. Optional atlas queries can return static skin and organ geometry.
- A busy science lock returns `busy`; run/job quotas return `resource_limit`.

See [source contracts](../src/human_models_mcp/server.py),
[official SDK examples](../examples/mcp-client/README.md) and
[trust boundaries](SECURITY.md). A scripted SDK test checks protocol behavior;
it is not a new LLM session or a validation of arbitrary agent conclusions.

## Research workflow

For push-up scenarios, add `visualization` to `run_scenario` to queue named
views on the same run. The reply includes the scientific gates and render
job IDs. Use `get_result` with a `gate:<name>` claim ID to inspect a specific
criterion. [Complete MCP, CLI and Python examples](PREVIEW_WORKFLOW.md)
