# v0.8.0 Research Preview handoff

The publication target is the existing [UsefulWrong repository](https://github.com/usefulwrong/human-models-mcp).
The verified v0.7.1 baseline is `c5bf297463333ee380573f0f96cb3ae5bdf941cc`.
Public `main` matched this revision at handoff.
Use the release title **Anatomical Grounding & Evidence v1**. The scientific
acceptance state is **PARTIAL**. Treat this as a research preview.

## What this version delivers

| Scope | Result |
| --- | --- |
| Native simulation | Existing scenarios, control laws and saved-state contract. The palm showcase includes residual joint assistance. |
| MCP and CLI | Four bounded push-up recipes, claim-level evidence and an optional right clavicular pectoralis render. |
| Motion reference | Private Fit3D input and geometric comparison. Synthetic controls exercise the software. Real Fit3D comparison was unavailable. |
| Local moving atlas | A separately scripted replay of 23 saved states. Full-resolution MyoSuite geometry replaces 62 arm parts. The fold fix passed its local gates on 57 parts. |
| Limits | Arm–bone and rib crossings, tendon attachments, intrinsic hand coverage and whole-body anatomical review remain open. The atlas visualizes skinning and display fits. |

- [Scientific scope and v0.8 evidence](../reports/V08_SCIENCE.md)
- [BodyParts3D registration](../reports/V08_ANATOMY_REGISTRATION.md) and [Fit3D benchmark status](../reports/V08_REFERENCE_BENCHMARK.md)
- [Earlier MCP and Blender verification](../reports/V08_RENDER_E2E.md) and [this publication run](../reports/V08_PUBLICATION_CHECK.json)
- [Whole-body coverage criteria](V08_MOVING_ATLAS.md) and [upper-limb replay and analysis](V08_UPPER_LIMB_REVIEW.md)
- [Code review and performance](../reports/V08_CODE_REVIEW.md)

## Prepared artifacts

| Artifact | Purpose |
| --- | --- |
| `human-models-mcp-0.8.0-source.tar.gz` | Full English source tree for review, including reports and the historical public demo. |
| `human-models-mcp-0.7.1-to-0.8.0.patch` | Update for a clean checkout at the verified v0.7.1 base. |
| `human_models_mcp-0.8.0.tar.gz` | Python source distribution with scripts, including the standalone arm replay, and no large media. |
| `human_models_mcp-0.8.0-py3-none-any.whl` | Installable Python package. Model provisioning uses the source checkout and pinned assets. |
| `human-models-mcp-0.8.0-atlas-preview.zip` | Separately licensed illustration, named measurements, editable scene and inputs for the exact local arm replay. |
| `SHA256SUMS` | Byte identity for the prepared archives. |

The Git source tree and Python packages contain no downloaded atlas meshes,
licensed Fit3D inputs, Blender binaries, or runtime job stores. The source
tree retains the earlier public demo and its original hashes. The optional
atlas archive carries its own attribution and applicable terms. [License notices](../notices/THIRD_PARTY.md) · [Atlas attribution](../notices/BODYPARTS3D.md)

## Replay from the preview archive

Extract the preview archive outside the source checkout, then run these
commands at the source root. Set `ATLAS_PREVIEW` to the extracted directory.

```sh
make render-build
python3 scripts/atlas_reference.py --accept-license CC-BY-4.0 \
  --mesh-quality hd --device gpu --output outputs/atlas-hd-reference
bash scripts/atlas_arm_replay.sh "$ATLAS_PREVIEW/replay-inputs/base.blend" \
  "$ATLAS_PREVIEW/replay-inputs/expected.json" \
  outputs/atlas-hd-reference/reference-atlas.blend outputs/atlas-arm-replay
```

The archive supplies the base scene already bound to the saved cycle and
the matching world-space record. The commands regenerate the arm fit,
scene, verified geometry report and video using the pinned source. The full
arm close-up recipe requires a supported OptiX GPU. The single-muscle
`pushup_anatomy` recipe supports CPU rendering through MCP and the CLI.
[Recipe commands and evidence scope](V08_ANATOMICAL_EVIDENCE.md)

## Operator publication

1. Compare the target branch with the known v0.7.1 base. Run
   `git apply --check human-models-mcp-0.7.1-to-0.8.0.patch` in an
   operator-owned clean checkout before applying it. Review the resulting
   files against the source export.
2. Run `python3 scripts/public_check.py --strict-tree` in the candidate public
   checkout. Check `SHA256SUMS` for any release assets selected for upload.
3. Run the CPU workflow on the actual commit and review its results. For
   any new visual or GPU claims, attach the matching renderer evidence.
4. The operator makes the commit, pushes, creates the `v0.8.0` tag and
   publishes the Research Preview. Keep experimental atlas data separate
   from the code distribution and carry the accompanying notices.

[Historical publication policy and v0.7.x handoffs](PUBLICATION.md)
