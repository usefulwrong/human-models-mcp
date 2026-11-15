# Release notes

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
