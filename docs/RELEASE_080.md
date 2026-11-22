# v0.8.0 — Anatomical Grounding & Evidence v1

Human Models MCP 0.8.0 is a Research Preview for model-specific experiments
with MuJoCo 3.17.0 and the pinned MS-Human-700 model. MCP, CLI and Python can
compute one push-up and queue bounded saved-state Blender 4.5.15 recipes.
The workflow returns run and job IDs, scientific acceptance and claim-level
evidence. Completed jobs expose checksum-verified media and editable scenes.
[Quick start](GETTING_STARTED.md) · [Four-view workflow](V08_WORKFLOW.md) ·
[MCP API](MCP_API.md)

- **Simulation** shows native geometry, joint axes and saved ground-reaction forces.
- **Muscle Activity** shows native musculotendon paths colored by recorded actuator activation.
- **Anatomy** shows bilateral Z-Anatomy rectus geometry fitted to saved sites.
  The optional right clavicular pectoralis overlay uses a separate BodyParts3D recipe.
- **Cinematic** uses the same saved states with studio lighting and materials.

The [public demo](demo/workflow/README.md) includes all four MP4s, matched
phase images, frame hashes, measurements, registration diagnostics and the
Evidence Contract. The showcased palm cycle uses fixed horizontal supports
and residual joint assistance. Its muscle-only criterion is **NOT_ACHIEVED**.
Overall anatomical acceptance remains **PARTIAL**. Regional fitting and
experimental moving-atlas skinning visualize geometry. The release leaves
tissue deformation and exercise safety unsupported and human experimental
validation **NOT_VALIDATED**. Real Fit3D comparison remains **NOT_RUN**.
[Scientific scope](SCIENTIFIC_SCOPE.md) · [Anatomical evidence](V08_ANATOMICAL_EVIDENCE.md) ·
[Moving atlas](V08_MOVING_ATLAS.md)

## Distribution

- The public source archive includes the four-view demo, historical demo,
  tests, notices and research reports. Use it for the documented Make and Docker workflow.
- The wheel contains the Python code and frozen package data. The compact
  sdist adds source, scripts, scenario definitions, tests and notices.
  Use the source archive or GitHub for the full linked documentation and media.
- Provision the locked model and Blender separately. Optional anatomy
  sources and private Fit3D data use their respective licenses and local
  provisioning. Keep local result stores and extracted third-party inputs
  out of the source release. [License and asset notices](../notices/THIRD_PARTY.md)

Earlier reports describe their own runs. [Historical v0.8 render report](../reports/V08_RENDER_E2E.md) ·
[Earlier publication check](../reports/V08_PUBLICATION_CHECK.json)

## Operator publication

Review the candidate against the current target branch. Verify the release
archive and package SHA-256 values, run the strict tree check in the candidate
checkout and confirm CI on the exact commit selected for publication. Publish
as **v0.8.0 Research Preview** with the scientific limits above. Include the
applicable attribution if distributing any separately generated atlas assets.
[Final release audit](../reports/V08_FINAL_RELEASE_AUDIT.md) ·
[Machine-readable checks](../reports/V08_FINAL_RELEASE_CHECK.json)
