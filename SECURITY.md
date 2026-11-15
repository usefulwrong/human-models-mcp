# Security

This is a local, single-user research tool, not an authenticated public HTTP
service or multi-user render farm. Use stdio; optional HTTP binds only to
container loopback and has no published port.

Read [trust boundaries and resource limits](docs/SECURITY.md) before connecting
an agent. Never provide patient records, credentials or unrelated host folders.

Report vulnerabilities privately through GitHub's **Report a vulnerability**
control if enabled. Otherwise open a minimal issue asking for a private contact,
without exploit payloads or sensitive details. No unverified contact address or
response-time commitment is provided.
