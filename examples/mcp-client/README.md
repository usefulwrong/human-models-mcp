# Official SDK clients

After `make build`, `make client` runs a real MCP client inside a new offline
container. `client.py --docker` connects from the host environment built in
`.client-venv`; `--compose PATH` selects an owner-controlled bundle configuration.
Select `pushup_flat_palm` to run the current experimental replay. `--save-dir`
exports every checked artifact to a new directory. Existing directories are refused.

```sh
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
.client-venv/bin/python examples/mcp-client/client.py --docker --scenario pushup_flat_palm --save-dir outputs/sdk-flat-palm --output outputs/sdk-flat-palm/client.json
python3 scripts/print_client_config.py
```

The generator prints a connector for the current checkout and edits no user
configuration. Do not run Make as a stdio connector. HTTP clients must share
the loopback namespace with the server; no host/LAN port is exposed.

`call_tool.py` forwards a chosen JSON tool call and records raw receipts.
`render_client.py` computes or reuses a saved run, submits a Blender job, waits
and downloads media using bounded chunks. `artifacts.py` and
`render_artifacts.py` verify hashes and sizes. These are scripted SDK clients,
not evidence of a new LLM conversation or biological validity.

[Tool guide](../../docs/MCP_API.md) · [Rendering](../../docs/RENDERING.md) ·
[Reproducibility](../../docs/REPRODUCIBILITY.md)

The 0.9.0rc2 Research Preview runtime uses Python 3.12 and the MCP SDK pinned
in `requirements.lock`. [Anatomy Lab SDK example](../../docs/V09_ANATOMY_LAB.md#query-anatomy_lab)
