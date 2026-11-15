# Local trust boundaries

This preview is single-user and local. Use stdio through Docker. HTTP binds
only to `127.0.0.1:8765` inside the container, has no published port, checks Host
and rejects browser Origins. It has no remote authentication or tenant isolation.
Do not advertise it as a public service.

MCP parameters are untrusted data. Fixed model IDs and strict bounded schemas
reject coercions, nonfinite values, unknown fields and arbitrary code/paths.
Scenario YAML is owner-installed configuration, parsed safely with size limits
and quarantined on errors. It cannot register a new solver or Python plugin.
Model XML/native libraries are trusted inputs; only locked, verified source files
are loaded. SHA-256 establishes byte consistency, not upstream authenticity or
scientific validity.

Provisioning downloads official HTTPS assets and hash-locked packages. Runtime
science and rendering have `network_mode: none`, dropped capabilities,
`no-new-privileges`, read-only roots, a non-root owner UID and bounded tmpfs/CPU/RAM/PIDs.
Science mounts project results, reports and render jobs; the renderer sees
science results read-only and writes only the render queue. No Docker socket,
home directory or unrelated host folder is mounted. The Docker daemon itself
remains a powerful trusted host service.

One process lock serializes science. Bounded workers have deadlines and
parent-death cleanup. Scientific artifacts are limited to 2 MiB each and 200
stored runs; renderer artifacts have separate chunked limits described in
[Rendering](RENDERING.md). Interrupted/failed runs and partial files remain
explicitly failed; stale status recovery does not delete evidence. There is no
automatic quota cleanup. Owner-selected `HMM_RESULTS_DIR` is not an MCP input.

Artifact access validates canonical UUIDs and manifest-listed flat filenames,
rejects traversal/symlinks and checks hashes. NumPy loading disables pickle and
checks headers/shapes/finiteness. Render requests select trusted layers/options,
not scripts, URLs or shell. Source results are snapshotted and hash-checked
before queueing. Host-local writable storage is trusted: an owner can rewrite
files, so hashes are not tamper-proof signatures against a hostile co-user.

Client exporters refuse existing destinations, check file names/sizes/hashes
and escape HTML. Direct Python execution lacks the Docker OS containment and
is for trusted local users. Optional GPU access relies on an existing host
runtime; no system or driver modifications are performed.

Do not place credentials, patient records, private scans or personal information
in results, requests or bug reports. Upstream academic contact details in the
licensed publisher XML are public scholarly metadata, not user records.
[Security reporting](../SECURITY.md).
