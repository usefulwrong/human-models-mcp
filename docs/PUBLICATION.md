# Public files, archives and operator handoff

The public repository is [usefulwrong/human-models-mcp](https://github.com/usefulwrong/human-models-mcp).
It is a source-checkout Research Preview, not a PyPI release, ready-to-run
public container distribution or clinical product. **This document describes
release work; it does not assert that the v0.7.1 GitHub release or DOI exists.**
The v0.7.0 public tree was already published; v0.7.1 is a patch update, not a
new repository creation.

## Retention matrix

| Material | Public Git tree | Prepared Release assets | Local research archive |
| --- | --- | --- | --- |
| Source, tests, scenarios, locks, skills, notices and current documentation | Yes | Also in the verified public source archive | Baseline preserved |
| One new palm demo: GIF, MP4, phase stills, passport, hashes and complete scientific data | Yes, under `docs/demo/` | Included with evidence | Full original export retained |
| Editable Blender scene, USD, every rendered frame and detailed audit records | No | Separate archive with licenses and SHA-256 | Original export retained |
| Source distribution and wheel | No | Checked code/data packages; no videos, downloaded models or Blender binaries | Build results retained |
| Earlier demo versions and historical operator/research reports | No | Not needed for the primary public example | Preserved with inventory; no historical experiment rewritten |
| LAN publication, agent input, browser logs, local paths and temporary Git handoff | No | Never | Ignored local storage only |

The exact prepared filenames, sizes, hashes and roles are in
[PUBLIC_RELEASE_ASSETS.json](../reports/PUBLIC_RELEASE_ASSETS.json). They are
**prepared for manual upload**, not already hosted downloads. The primary demo
and its scientific data are already present in the public source tree and do
not depend on those uploads.

## Publishing safely

For **v0.7.1**, update the existing public repository using the cumulative
`0.7.0 → 0.7.1` patch provided by the maintainer. First verify that the public
working tree matches the patch's base: `git apply --check` must succeed without
fuzzy fallback. The patch includes the nested-archive privacy guard and improved
README/contributor documentation; the earlier stand-alone patch is not needed.
Apply it only in a clean worktree, then run the new public-check gate and CPU
workflow, and perform a separate host rendering/GPU acceptance where available.
The actual release tag, GitHub asset URLs and any DOI are operator decisions.
See [upgrade steps](RELEASE_071.md).

For a **new mirror/export**, use a verified public source archive rather than
pushing any previously private history. Excluding files from the current tree
does not erase them from old Git commits. Do not change historical scientific
manifests to imply they were recomputed for a documentation-only release.

For an operator who chooses to keep private history locally, tracked deletions
of archived documents and reports must be recorded by that operator. `.gitignore`
does not remove already tracked files. The public source archive provides a
checked alternative that cannot accidentally include those old index entries.
Do not use an unfiltered tar of the working directory or `git archive HEAD`:
HEAD may not contain the release work and private history is outside the
reviewed delivery surface.

## Manual publication checklist

1. Check the exact public `main` base and backup any local work. On the working
   repository run `git apply --check` with the delivered cumulative patch.
   **Stop on a mismatch**; the archived 0.7.0 export is the patch base, not
   independent proof that an unseen GitHub tree has identical bytes.
2. Apply the patch, inspect `git diff`, `git diff --check`, and run
   `python3 scripts/public_check.py --strict-tree` on the prospective public tree.
   This checks links, demo hashes and known privacy patterns including nested
   ZIP/NPZ entries; it cannot prove arbitrary binaries are free of secrets.
3. Run `make build`, `make test`, `make e2e`, `make pushup-e2e` on the target
   Linux/Docker machine. Independently check `make render-build` and
   `make render-e2e` if claiming fresh visual E2E; GPU is optional and separate.
4. Make the human-reviewed commit, push and inspect **the new workflow run** on
   the v0.7.1 commit. A previously passing v0.7.0 workflow is useful history,
   not evidence that the updated commit passed.
5. Only after these checks create the `v0.7.1` Research Preview tag/Release;
   attach only audited files whose actual hashes match the release inventory.
   Optional: archive the tag with Zenodo; do not invent a DOI.

The v0.7.0 [RC audit](../reports/PUBLIC_RELEASE_AUDIT.md) and its machine report
remain **historical evidence**, not new measurements for v0.7.1. Keep that
provenance visible in release notes and scientific publications.

No Docker image is prepared for public redistribution here. If you redistribute
one later, review all dependency/source obligations, including Blender GPL and
Debian/FFmpeg components. Building and using a local renderer is separate from
publishing its binaries. [License details](../notices/THIRD_PARTY.md).
