# Updating the public repository: 0.7.0 → 0.7.1

This is a **patch upgrade of the existing public GitHub repository**. The cumulative
patch contains the previously prepared nested-archive verification changes *and*
the clearer public README/CONTRIBUTING and release documentation. Do **not** apply
the older, separate 0.7.1 patch first.

No physics, controller settings, model hashes, saved numerical states or Blender
demo media have been changed. The demo's scientific passport correctly continues
to identify the original **0.7.0 calculation**. A documentation/integrity update
does not justify relabeling it as a fresh 0.7.1 simulation.

## Prerequisites and base verification

1. Use an unmodified checkout of the published `main` containing wrapper
   version **0.7.0**. The patch was generated from the provided
   `human-models-mcp-0.7.0-public-source.tar.gz` (SHA-256
   `67a5ff81525e18881ac8c3abacea617d5d071f15b6c1a96b3da550de52d907cd`).
   **That archive may differ from the live GitHub tree**, which must be checked
   on the operator's machine; do not infer byte equality from a passing old CI.
2. Keep any uncommitted work outside the target tree. Check `git status --short`
   and ensure the patch will not overwrite unrelated changes. Do not run
   destructive Git reset/clean commands.
3. Place the delivered cumulative patch outside the repository, e.g. in its
   parent directory. Never download a patch from an untrusted link and execute
   it without inspecting the diff.

```sh
# From the existing Git checkout, before applying:
git status --short
git apply --check ../human-models-mcp-0.7.0-to-0.7.1-PUBLIC.patch
# Stop here and request a patch rebased on your exact tree if the check fails.
git apply ../human-models-mcp-0.7.0-to-0.7.1-PUBLIC.patch
git diff --check
git diff --stat
```

## Verify the changed tree

```sh
python3 scripts/public_check.py --strict-tree
export HMM_UID="$(id -u)" HMM_GID="$(id -g)"
make build
make test
make e2e
make pushup-e2e
```

The strict public checker scans relevant nested ZIP/NPZ entries, demo hashes,
relative links and common privacy markers. It is not a virus scanner or a
human scientific/clinical validation. On a working checkout with extra
unpublished notes, it may fail closed; remove those notes from a **copy** of the
export and check again rather than weakening the gate.

If publishing a new rendering-test claim, perform the real Blender route:

```sh
make render-build
make render-e2e
```

GPU testing is optional, separate and requires a correctly configured NVIDIA
container host; a CPU PASS is not a GPU PASS. The v0.7.0 GitHub Actions result
and earlier RC audit are historical, not proof of the newly patched tree.

## Publish only after review

The operator performs `git add`, commit, push and tagging. Inspect the new
[Actions run](https://github.com/usefulwrong/human-models-mcp/actions) for the
patched commit, then create `v0.7.1` as **Research Preview**. Do not overwrite
existing release notes or invent a DOI. For an externally attached ZIP/wheel,
verify its own manifest and SHA-256 rather than assuming a source patch also
validated the new binary distribution.

See [Contributing](../CONTRIBUTING.md), [Scientific scope](SCIENTIFIC_SCOPE.md),
[Demo passport](demo/README.md), and [Public files](PUBLICATION.md).
