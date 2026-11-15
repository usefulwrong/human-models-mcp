# Contributing

Start with a focused issue describing a bug, reproducibility failure or scientific
discrepancy. This preview is in feature freeze: avoid new models, exercises,
control methods and broad refactors in release fixes.

```sh
make build
make test
make e2e
make pushup-e2e
python3 scripts/public_check.py
```

Use Linux x86-64 and the pinned Docker environment. Rendering changes also need
an actual saved-state Blender render and independent media/geometry checks;
see [Rendering](docs/RENDERING.md). Fast CI does not replace the full local RC.

Keep fixes small. Preserve old states, manifests and hashes. Give a concrete
reproduction, expected/actual behavior, versions, commands and test evidence.
Do not include credentials, personal paths or private server addresses. Use the
scientific issue template for coordinate, unit, reference-data or provenance
problems.

Follow [AGENTS.md](AGENTS.md) before scientific changes: inspect human references
before changing movement geometry, preserve rejected experiments, separate model
results from human measurements and disclose external forces. New assets need
explicit provenance and redistribution terms.

Submitted code must be distributable under the wrapper's [MIT license](LICENSE).
Retain separate third-party notices. Use [Security](SECURITY.md) for vulnerabilities.
