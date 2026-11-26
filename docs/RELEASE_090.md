# Human Models MCP 0.9.0rc2 Research Preview

The full source tree provides the Linux and Docker workflows. Wheel and sdist
provide the Python package and its build inputs. Use `human-models-mcp --version`
to check the installed core.

[Current replay and source receipts](demo/README.md) · [Run and inspect the experiment](PREVIEW_WORKFLOW.md)

| Capability | Status | Evidence and interpretation |
| --- | --- | --- |
| Articulated `pushup_flat_palm` replay | SUPPORTED | 111 saved states on the pinned model. Browser, Blender and MCP share the exact state clock. |
| Distributed palm and digit contact | PASS | The named contact regions pass the engineering load criterion. |
| Full movement and numeric checks | FAIL | The full push-up, four-support, stationary-support and numerical-bound checks fail. |
| MS-Human-700 native signals | SUPPORTED | 700 actuators. Excitation, activation, signed force, length, velocity and power are model outputs. Force magnitude and sampled work are derived. |
| BodyParts3D 4.3 atlas | OPTIONAL | Install pinned local geometry and FMA/FJ source records. The authored 4.3i inference graph remains unverified. |
| Crosswalk and moving surfaces | PARTIAL / ILLUSTRATIVE | The current run has 76 reviewed sided-group associations, 74 exact FMA identities, 354 candidates and 270 unassigned rows. The display has 288 moving muscle surfaces. |
| Muscle-only control | NOT_ACHIEVED | External residual joint control is used. |
| Human experimental validation | NOT_VALIDATED | Surface EMG, pressure, calibrated tissue deformation and clinical use require different evidence. |

On Linux, the [getting-started guide](GETTING_STARTED.md) covers Docker and
offline use with provisioned inputs. See [third-party notices](../notices/THIRD_PARTY.md)
and [publication checks](PUBLICATION.md).
