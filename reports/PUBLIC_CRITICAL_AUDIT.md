# Critical public RC audit

Separate review pass on 2026-11-12, taking the positions of a first-time developer
and a skeptical researcher. This is a release-agent review with independently
executed checks, not an external peer review or a human experiment. The current
execution verdict is in [PUBLIC_RELEASE_CHECK.json](PUBLIC_RELEASE_CHECK.json).

## First-time developer

| Question | Evidence / finding | Disposition |
| --- | --- | --- |
| Can I understand the project without opening an internal report? | The README gives one real animation, an immediate assistance disclosure, Run/Science entry points and a small control-method table. | Pass |
| Does the demo actually exist in the source tree? | GIF, MP4, three stills, passport, frame clock and complete data are under `docs/demo/`; no unpublished Release URL is required. | Pass |
| Will installation work outside the author's account? | A real UID 1001 failure was reproduced. Compose now maps owner IDs; Make and SDK clients propagate them, and the printed connector selects its user. A fresh scientific MCP run succeeded as UID 1001. | Fixed and checked |
| Are the commands complete? | Clean-tree runs execute the README build, CPU preview, numeric launcher, connector generator and CLI. Output reuse is deliberately refused. Platform, storage and first-download requirements are stated. | Pass on the tested Linux stack |
| Can I inspect and reproduce without AI? | Independent SDK/CLI exports expose manifests and all scientific bytes. No API key, LLM session, original workstation path or NVIDIA device is required for CPU execution. | Pass |
| Will a package unexpectedly contain the old research archive? | The sdist uses text documentation and explicit project data, with a 2 MiB guard; videos/scenes/downloaded models are excluded. Wheel/sdist are code packages, not standalone model databases or the main demo distribution. | Fixed and checked |
| Can old private material enter through Git? | 488 tracked historical/operator paths fall outside the reviewed public set. A fresh public source export excludes `.git` and all local archives. Publishing old history is explicitly excluded from this handoff. | Use the clean publication input |
| Is the CI meaningful? | Pinned official Actions, read-only token permissions, real CPU unit/scientific/MCP/package commands, no GPU or secrets. Commands are exercised locally; GitHub scheduling itself awaits the operator's first push. | Configured; hosted execution not claimed |

## Skeptical researcher

| Challenge | Evidence / limitation | Disposition |
| --- | --- | --- |
| Is an assisted animation being sold as muscle-only? | The hero is `pushup_palms` 1.5.0. Its passport says external control USED and muscle-only NOT_ACHIEVED. `pushup` 1.0.0 is a different configuration, tested separately with zero external joint/body forces in muscle mode. | Claims separated |
| Was anatomy widened to make this release look better? | No model, controller or trajectory was changed during RC work. The pre-existing two-bound wrist derivative is prominent, versioned, literature-informed and explicitly uncalibrated. | No new scientific modification |
| Does numerical PASS establish a valid human push-up? | No. Gates test named model behavior, contacts and residuals. Source scapular coupling, passive damping, proxy contacts, rigid fingers and incomplete body-floor geometry remain. | Scope stated |
| Are hands fixed because friction predicted it? | Horizontal sticking is prescribed through guides. Their reactions enter the force/friction checks, and residual motion is measured. This is not a calibrated skin/friction prediction or literal zero displacement. | Boundary disclosed |
| Are colors evidence of EMG or anatomical muscle volumes? | Colors use saved activation. The displayed 418 routes are an overlapping subset of 700 actuator traces; six PECM1–3 paths are separately available. Group means and summed path-force magnitudes are not measured EMG, causal importance or net chest force. | Correctly labeled |
| Could Blender conceal a different motion? | Source hashes are unchanged; native replay, USD/baked-scene geometry, overlays and clocks are checked. MP4 frames are independently compared with numbered PNGs, and all GIF frames are decoded. CPU/GPU rendering does not integrate physics. | Transfer checked |
| Is playback physical time? | The 51-frame MP4 lasts 4.25 s, GIF 4.08 s, physical cycle 4.4 s. Frame captions/passport preserve the true time and GIF quantization. | Clocks disclosed |
| Is there an independent repeat? | Two newly computed palm runs have identical decoded states, CSV and trajectory SHA-256 on the tested stack. Original push-up tests also repeat and include zero-strength, low-friction, external-control and timestep controls. | Numerical repeatability only |
| Were real people used as a visual reference? | ACE top/bottom photographs and the primary MDPI Figure 1 were viewed alongside the simulation phases. Hands/arm motion and a plank-like cycle are recognizable. These are unregistered images; no independent human return sequence, synchronized kinetics or subject calibration is supplied. Photographs are not redistributed. | Qualitative check, not validation |
| Are licenses and citations being inferred from a generic project name? | The pinned model license and OpenUSD notice match upstream bytes. Blender-generated artwork is distinguished from redistributing its GPL program. CFF validates against the official 1.2.0 schema. Publisher XML retains its own CC0 attribution. | Selected assets reviewed |
| Is GPU status based only on `nvidia-smi`? | The host probe failed, but a Docker Cycles probe and actual RTX 3070 Ti OptiX render succeeded; a separate no-GPU request genuinely fell back to CPU. | Actual backend recorded |

## Remaining limits

No clinical, patient-specific, injury, ligament, soft-tissue or whole-human
experimental validation is established. Visual agreement and reproducibility
cannot supply those missing experiments. Source hand reconstruction shares the
reviewed derivation helper with the exporter: independent geometry checks test
transfer against the solver, not an independent anatomical derivation.

Linux x86-64 Docker is the tested platform. OS apt packages are inventoried but
not snapshot-pinned; future cross-platform or bitwise pixel identity is not
promised. Automated access restrictions on some external publishers are
recorded separately; no broken relative file is accepted. GitHub publication,
its first hosted CI run and any later container-binary redistribution remain
operator work.

No unresolved publication blocker was found in this reviewed source/data surface
after the ownership, packaging and documentation fixes. Publication still
requires a passing final machine verdict and the exact clean source export;
this review does not approve pushing the private repository's old history.
