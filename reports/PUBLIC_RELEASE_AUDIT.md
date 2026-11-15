# Public Research Preview RC audit

**PUBLIC_RC_READY — 0.7.0 / UsefulWrong**, checked 2026-11-12T16:12:24.493802+00:00.
This is a source-publication candidate, not a published release. No Git mutation,
tag, remote push, GitHub publication or driver change was performed.

## What was verified

Three new source-tree fixtures started without prior results, output media,
models, venvs or Blender downloads. Each provisioned the 251 locked model files.
The first science/renderer images were explicitly built without cache; final
acceptance rebuilt the delivered source with the documented Make commands.
Old 77/83/91-test reports were not counted as this acceptance. **95 tests passed
in 177.21 s** after code fixes; full CPU E2E, stdio/HTTP SDK clients, original
push-up controls, CLI and actual Blender media passed again.

| Final clean-tree command | Exit | Seconds |
| --- | ---: | ---: |
| `make render-build` | 0 | 130.112 |
| `make render-preview` | 0 | 62.333 |
| `make test` | 0 | 179.639 |
| `make e2e` | 0 | 238.759 |
| `make pushup-e2e` | 0 | 55.815 |
| `make build` | 0 | 4.571 |
| `python3 scripts/experiment.py --scenario pushup --output outputs/my-pushup` | 0 | 10.280 |
| `python3 scripts/print_client_config.py` | 0 | 0.032 |
| `make client` | 0 | 3.169 |
| `python3 scripts/visualize.py list-profiles` | 0 | 0.415 |
| `python3 scripts/public_check.py` | 0 | 0.164 |

The literal three-line README export/build/preview block also passed (exit 0,
125.323 s). The actual generated TOML connector was parsed and
executed by a separate official SDK client, including a new knuckle run and
medical/path refusals. No new LLM conversation is implied. Full commands,
original/public-copy log hashes and independent checks are in the prepared
`human-models-mcp-0.7.0-rc-evidence.zip` asset.

Runtime: Python 3.12.16, MuJoCo 3.17.0, MCP SDK 2.3.0,
Blender 4.5.15; host launchers Python 3.13.9; Docker
29.9.1, Compose 5.6.0. Physics remains CPU.

## Scientific result and visible evidence

The public hero is a newly computed **assisted** `pushup_palms` 1.5.0 run,
`9ed1e5d7-40b9-4d4c-96f8-8fcc98e6ac1b`. Native 700-actuator recruitment is supplemented by
recorded external joint assistance; muscle-only is NOT_ACHIEVED. Its chest
excursion is 27.865 cm, maximum horizontal support displacement
0.0946 mm, and external joint work 578.014 J.
These are model outputs, not measurements from a person. Two newly computed
palm runs have identical decoded states, CSV and trajectory SHA-256.

The separate `pushup` 1.0.0 muscle mode passed with zero external joint/body
forces; zero-strength and low-friction controls failed as expected. A new
`pushup_knuckles` 1.2.0 default also passed its own gates while retaining external
assistance USED. No pure-muscle status was transferred between configurations.
The existing two-bound palm wrist derivative is explicitly uncalibrated; no
scientific code, model, controller or reference trajectory changed in RC work.

[Demo and complete scientific data](../docs/demo/README.md) ·
[Passport](../docs/demo/passport.json) · [Frame clock](../docs/demo/frames.json) ·
[Scope](../docs/SCIENTIFIC_SCOPE.md).

The 51-frame CPU MP4 and GIF were decoded; start/bottom/return PNGs and human
reference photographs were actually viewed. No reference photograph is shipped.
Independent source reconstruction, reopened baked Blender geometry, overlays,
clock and full-video checks passed. MP4-vs-PNG sampled PSNR is above 36 dB;
all GIF frames exceed 32 dB, using disclosed engineering transfer guards.
Video duration is 4.25 s, GIF 4.08 s and physical duration 4.4 s; these clocks
are deliberately distinguished. Images are solver-state renderings, not generated
anatomy illustrations.

GPU was actually checked: although host `nvidia-smi` failed, Docker Blender
found RTX 3070 Ti and completed an **OptiX** render, independently audited.
A separate no-GPU HTTP render genuinely used CPU fallback. Those outcomes are
recorded separately, without counting fallback or enumeration as GPU success.

## Publication defects fixed

- Replaced local-only viewer links and a stale external MuJoCo state anchor;
  the primary demo and all its scientific data now exist in the public tree.
- Removed historical demo media/reports from the public surface after preserving
  27,921 original files (4,318,345,729 bytes) with a SHA-256 inventory locally.
  Original results and past rejected experiments were not rewritten or deleted.
- Restricted sdist contents: old build was about 113.6 MB; the new code sdist
  is 388,933 bytes, without media, downloaded models or Blender binaries.
  Wheel/sdist are optional code packages, not a standalone model database.
- SDK clients now preserve the selected image/project/store settings instead of
  silently connecting to an older default image. Offline-bundle Compose serialization
  removes build/pull dependencies while retaining immutable image IDs.
- Reproduced the UID 1000/1001 ownership failure and fixed owner-ID propagation
  through Compose/Make/SDK and generated connectors. A real scientific run under
  UID 1001 passed; no world-writable main result stores are required.
- Added short source-based documentation, CFF references, community/security files,
  bounded package checks, an offline public asset/link checker and pinned CPU CI.

Final runtime source/config/tests match the tested clean copy. Two later
**documentation-only** corrections (historical viewer wording and the state-anchor
URL) were checked through the final link/asset and Python 3.12 package rebuild.

## Links, licenses, privacy and package boundaries

The offline [link/asset report](PUBLIC_LINK_CHECK.json) accepts no missing public
file or relative anchor. [External checks](PUBLIC_EXTERNAL_LINKS.json) cover
50 URLs, including source registries and HTML anchors: 46 returned successful
responses; four official publisher/Blender URLs restrict automated access with
403. These restrictions are retained, with independent article/license review
and a working official Blender source mirror. There are no known 404s or stale
external anchors after the fix. Required model/Blender downloads were actually
retrieved and hash-verified from clean stores.

CFF passes the official 1.2.0 JSON Schema. Retained model, MuJoCo and OpenUSD
notices match pinned upstream bytes; the publisher XML matches a new download
and retains CC0 attribution. Wrapper MIT, Apache model derivatives and the GPL
Blender program are distinguished. No Blender binary/image, external atlas,
third-party photograph or patient data is redistributed in the prepared assets.

Public source/data and nested ZIP/NPZ members were scanned for private paths,
private IPs, key headers and common credential forms. QA log copies additionally
redact checkout/temp paths and infrastructure mirror names; original local logs
are preserved. The publication export excludes `.git`, local outputs and private
history. **488 tracked historical/operator paths** fall outside it. An operator
keeping the private repository must record those exclusions; pushing its old
history is not approved by this handoff. Use the clean publication input.

The standalone wheel contains code plus the frozen reference; project locks,
scenarios and provisioned models are still required. The documented full-source
checkout route was tested. No PyPI-ready or cross-platform installation claim
is made. Apt versions are inventoried, not snapshot-pinned.

## Prepared operator artifacts

These are prepared locally, not uploaded or represented by invented URLs.
Exact roles are in [the asset inventory](PUBLIC_RELEASE_ASSETS.json).

| Prepared file | Bytes | SHA-256 |
| --- | ---: | --- |
| `human-models-mcp-0.7.0-palms-scene.zip` | 49,352,376 | `7dd25c7280a6b0bd5cc0b37a64dbb91ef9ce85d40c9b030e03962af0d11c0780` |
| `human-models-mcp-0.7.0-rc-evidence.zip` | 3,956,018 | `8cfa45964112d04fb5d0c1ffd55c5289d9ea9c63cb4f9f7df01e97f3eddb581f` |
| `human_models_mcp-0.7.0.tar.gz` | 388,933 | `5e461287874bbc1c8ebb2e4504a1cfc5c563eaec97c5c7a79a3275fdd3aee1b7` |
| `human_models_mcp-0.7.0-py3-none-any.whl` | 123,977 | `6766e17b1cf883a8e74862ace8a0f1005ceeb952fed9af56e3e8d675eeb90f8f` |

The complete clean publication input is
`human-models-mcp-0.7.0-public-source.tar.gz`. Its detached checksum is in
`SHA256SUMS` / `PUBLISH.json` beside it, avoiding an archive self-hash cycle.
The same verified tree is available in the local `public-tree/` handoff directory.
The scientific demo/data need none of the unpublished optional Release assets.

## Independent final review and manual actions

The [separate critical audit](PUBLIC_CRITICAL_AUDIT.md) challenges first-use
instructions, control attribution, geometry, units, repeatability, licensing,
privacy and unsupported human interpretations. No unresolved public-source
blocker remains on the tested Linux x86-64 Docker stack. Human/clinical,
ligament and soft-tissue validation remain absent; hosted GitHub CI has not run.

Two honest release-note sentences:

> New clean-tree CPU experiments, SDK/CLI transfers and saved-state CPU/OptiX
> renders passed numerical and artifact checks on the tested Linux stack.
> The assisted palm/fist derivatives are not muscle-only or human/clinical
> validation; source contact, wrist and tissue limitations remain.

Operator steps:

1. Verify the clean source archive against its detached checksum and extract it
   into a fresh directory; run `python3 scripts/public_check.py` there.
2. Create the intended UsefulWrong GitHub repository and perform the initial
   commit/push from that tree, without the old private history.
3. Run and inspect the first hosted CPU workflow; no hosted run is claimed here.
4. Create the Research Preview release manually using [release notes](../CHANGELOG.md)
   and upload the selected prepared assets exactly as listed. Add actual hosted
   URLs only after they exist. Private vulnerability reporting/Pages are optional.

Input-specification note: `CODEX_GITHUB_RC.md` was absent. The supplied detailed
`HUMAN_MODELS_MCP_GITHUB_RELEASE_RC_HANDOFF.md` was read completely and applied
alongside the user's inline task; its exact SHA-256 is retained in the machine
report. No missing file was claimed to have been read.
