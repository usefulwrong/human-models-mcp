# Release notes

## 0.8.0 — Anatomical Grounding & Evidence v1

- Added claim-level Evidence Contract retrieval and render evidence artifacts.
- Added optional BodyParts3D clavicular pectoralis replay and phase-specific registration diagnostics.
- Added bounded push-up render recipes and verified local atlas provisioning.
- Added a private Fit3D motion importer, kinematic comparison and skeleton overlay.
- Added the optional MyoSuite whole-body source preview and a scripted local
  replay with full-resolution geometry for 62 arm parts, a bilateral distal fit,
  and a verified fold repair on 57 surfaces.
- Render recipe reuse now includes renderer lock digests. Artifact manifests
  and evidence share the same verified metadata.
- Preserved the v0.7.1 simulation scenarios and results contract. Anatomical
  acceptance remains **PARTIAL**. See the [v0.8 handoff](docs/RELEASE_080.md).

## 0.7.1 — Public release hardening and contributor onboarding

Release hardening and public documentation only: existing MuJoCo calculations,
controller recipes, scenario configurations and demo assets are unchanged.
The README now introduces the scientific purpose and limitations, explains a
complete first experiment and real MCP connection, and distinguishes native
muscle control from the externally assisted showcase. The contributing guide
now covers independent research reports, reproducible tests, numerical evidence,
licensing, security and AI-assisted PRs. Publication instructions now describe
upgrading the *existing* UsefulWrong GitHub repository from v0.7.0. A strict public-tree
check rejects unreviewed files in an exported source archive. The public
validator now scans ZIP/NPZ members recursively without extracting them,
checks archive entry paths/duplicates/CRC and limits decompressed sizes,
including the embedded scientific evidence archive. Regression tests cover
private text and path traversal hidden inside nested ZIPs.

The public demo was generated with v0.7.0; its original passport, scientific
results, and hashes have not been rewritten. Prior RC reports remain historical
evidence for v0.7.0; they are not an independent Docker/GPU E2E for v0.7.1.
See [Publication](docs/PUBLICATION.md) and [v0.7.1 upgrade](docs/RELEASE_071.md)
for the clean-tree guard and target-host verification. No new clinical, anatomical, or biomechanical claim is made.

## 0.7.0 — Public Research Preview RC

This RC packages the existing 0.7.0 engine and later palm/knuckle improvements.
Release work changes installation, documentation, packaging and evidence, not
the scientific algorithms. It has not been published or assigned a DOI.

Original `pushup` uses native muscle recruitment with zero external joint/body
forces in muscle mode. `pushup_palms` 1.5.0 provides the full palm cycle with
explicit external residual joint assistance and a literature-informed wrist
derivative. `pushup_knuckles` 1.2.0 uses neutral fists and tucked elbows, also
with external assistance. Their results are separate.

The public demo is regenerated from a new experiment. Raw data, frame clock,
hashes and licenses accompany it; large editable scenes and frame archives are
prepared separately for the operator. Historical experiments remain in a local
archive and are not relabeled as new RC evidence.

Release fixes remove local-only links, isolate operator materials, bound source
package contents, and add a public asset/link checker and small CPU CI. Default
Compose names retain `-night` for compatibility with existing stores; user
commands use Make. Image tags and the preview project can be isolated through
environment variables during release testing.

The current status and actual commands are in [the RC audit](reports/PUBLIC_RELEASE_AUDIT.md).
CPU reproducibility and visual transfer checks do not establish clinical accuracy,
human push-up validation, ligament mechanics or cross-platform equivalence.
GPU status is reported separately; this project does not install drivers.
