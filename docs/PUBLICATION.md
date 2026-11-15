# Public files, archives and operator handoff

The public repository is a source-checkout Research Preview, not a PyPI release,
container distribution or clinical product. No GitHub repository URL or release
asset URL is invented before the operator creates it.

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

Use the verified public source archive named in the asset inventory as the
publication input. It excludes `.git`, local outputs and historical operator
materials. Start a fresh public repository from that tree; do not push the
private working repository's old history. Old commits can retain author paths
and internal records even after current-tree cleanup. This task does not rewrite
history, stage files, commit, tag or publish.

For an operator who chooses to keep private history locally, tracked deletions
of archived documents and reports must be recorded by that operator. `.gitignore`
does not remove already tracked files. The public source archive provides a
checked alternative that cannot accidentally include those old index entries.
Do not use an unfiltered tar of the working directory or `git archive HEAD`:
HEAD may not contain the release work and private history is outside the
reviewed delivery surface.

## Manual publication checklist

1. Read the current [RC audit](../reports/PUBLIC_RELEASE_AUDIT.md) and confirm
   `PUBLIC_RC_READY` in the machine-readable report.
2. Verify the public source archive SHA-256, extract it into a new directory,
   run `python3 scripts/public_check.py`, and review that exact tree.
3. Create the intended UsefulWrong GitHub repository and make the initial commit
   from that clean tree. Run its CPU workflow and inspect the actual Actions result.
4. Create the Research Preview release manually, using [release notes](../CHANGELOG.md),
   and upload the prepared assets exactly as listed. Check downloadable bytes.
5. Optionally enable private vulnerability reporting and a static Pages host for
   `docs/demo/`. GitHub's source view does not execute local HTML. The README GIF
   and MP4 links work without Pages. Add real URLs only after they exist.

No Docker image is prepared for public redistribution here. If you redistribute
one later, review all dependency/source obligations, including Blender GPL and
Debian/FFmpeg components. Building and using a local renderer is separate from
publishing its binaries. [License details](../notices/THIRD_PARTY.md).
