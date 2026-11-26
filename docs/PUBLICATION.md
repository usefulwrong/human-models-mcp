# Public source and release assets

Human Models MCP 0.9.1rc1 is a Research Preview candidate for the
[public repository](https://github.com/usefulwrong/human-models-mcp).
The reviewed source archive includes the documentation, workflows, tests,
notices and the current preview media and passport. Generated
result stores and provisioned inputs belong in local storage.
The preview shows the articulated `pushup_flat_palm` experiment with its
recorded failures. The source includes both hand close-ups and an Anatomy
Explorer capture with source-specific credits. [Current demo and credits](demo/README.md)

| Deliverable | Contents |
| --- | --- |
| Public source archive | Local Compose/MCP workflows, optional atlas scripts, scenarios, pinned inputs and offline-linked demo media |
| Windows x64 bootstrap ZIP | Unsigned portable launcher, project sources, notices and platform locks |
| SHA256SUMS | Checksums for the public source and Windows ZIPs |
| Wheel and sdist | Core Python distribution and compact build inputs, respectively |
| Demo media | Versioned renders, signal plots, receipts and per-asset attribution |
| Optional editable scene | Separately distributed geometry and credits, with SHA-256 |

Use the [asset notices](../notices/THIRD_PARTY.md) to determine the terms for
each input and derivative. Retain historical manifests and acceptance
statuses with their original versions.

Generate and check the two public ZIPs in a local output folder.

```sh
python3 scripts/windows_package.py --output release/0.9.1rc1
```

Provider binary archives, model caches, BodyParts3D metadata and crosswalks
remain outside the public ZIPs. Publish after reviewing platform acceptance.

## Publication checklist

1. Verify SHA-256 for the source archive, packages and each proposed attachment.
2. Extract the archive and run `python3 scripts/public_check.py --strict-tree`
   in the extracted source directory. Review the inventory of intended paths
   against the prospective public file list and Git diff. Existing Git history
   can contain material outside the current release inventory.
3. Confirm the recorded checks and version for the exact publication payload.
   Run the CPU workflow against the selected commit before creating a tag.
4. Recheck public tags and releases before choosing a version. Carry the
   actual articulated-palm and full-cycle checks into the release description.
5. Create the release manually and attach only the files listed in the
   release checksums. Publish the asset credits with the corresponding files.

[Release notes](RELEASE_090.md) · [Reproducibility](REPRODUCIBILITY.md)
