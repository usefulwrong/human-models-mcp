"""Check the deliverable tree, relative links and demo bytes without network access."""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
import zipfile
import zlib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("src", "scenarios", "scripts", "tests", "skills", "examples", "notices", "benchmarks", "docs", ".github")
ROOT_FILES = ("README.md", "AGENTS.md", "LICENSE", "CITATION.cff", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md",
              "pyproject.toml", "MANIFEST.in", "Makefile", "Dockerfile", "Dockerfile.render", "compose.yaml",
              "compose.render-gpu.yaml", ".gitignore", ".dockerignore", "Dockerfile.render.dockerignore",
              "requirements.in", "requirements.lock", "requirements-render.lock", "models.lock.json",
              "renderer.lock.json", "visual_sources.json")
REPORTS = ("PUBLIC_RELEASE_CHECK.json", "PUBLIC_RELEASE_AUDIT.md", "PUBLIC_RELEASE_ASSETS.json",
           "PUBLIC_LINK_CHECK.json", "PUBLIC_EXTERNAL_LINKS.json", "PUBLIC_CRITICAL_AUDIT.md",
           "V08_SCIENCE.md", "V08_ANATOMY_REGISTRATION.md", "V08_REFERENCE_BENCHMARK.md",
           "V08_RENDER_E2E.md", "V08_RELEASE_CHECK.json", "V08_CODE_REVIEW.md", "V08_PUBLICATION_CHECK.json",
           "V08_FINAL_RELEASE_AUDIT.md", "V08_FINAL_RELEASE_CHECK.json")
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
PRIVATE = {
    "personal_path": re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/"),
    "private_ipv4": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    "private_key": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    "credential": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b"),
}


def public_files(root):
    paths = [root / name for name in ROOT_FILES if (root / name).exists()]
    for name in DIRECTORIES:
        paths.extend(p for p in (root / name).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and not any(x.endswith('.egg-info') for x in p.parts))
    paths.extend(root / "reports" / name for name in REPORTS if (root / "reports" / name).exists())
    return sorted(paths)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src", "poster") and value and value != 'data:,':
                self.links.append(value)
            if key == "id":
                self.ids.add(value)


def anchors(path):
    content = path.read_text()
    if path.suffix == '.html':
        parsed = Links()
        parsed.feed(content)
        return parsed.ids
    found = set()
    counts = {}
    for line in content.splitlines():
        if re.match(r'^#{1,6}\s', line):
            title = re.sub(r'^#+\s+', '', line).strip().lower()
            title = re.sub(r'[^\w\-\s]', '', title).replace(' ', '-')
            count = counts.get(title, 0)
            counts[title] = count + 1
            found.add(title + (f'-{count}' if count else ''))
    return found



# Archive members are explicitly validated: checking only the ZIP hash would
# not reveal accidental inclusion of a private note in an otherwise valid demo.
ARCHIVE_SUFFIXES = {".zip", ".npz"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".xml", ".csv", ".yaml", ".yml",
                 ".toml", ".cff", ".ini", ".cfg", ".py", ".sh", ".html", ".env", ".log"}
ARCHIVE_MAX_MEMBER = 32 * 1024 * 1024
ARCHIVE_MAX_TOTAL = 256 * 1024 * 1024
ARCHIVE_MAX_DEPTH = 4
# These are local runtime artifacts, not files to include in the public export.
LOCAL_ONLY = {".git", ".venv", ".client-venv", "__pycache__", ".pytest_cache",
              ".ruff_cache", ".cache", "dist", "build", "results", "release",
              "outputs", "output", "render_vendor", "render_jobs", ".agent-input",
              ".playwright-mcp", ".agents", ".codex"}


def scan_archive_bytes(payload, location, failures, budget, depth=1):
    """Inspect nested ZIP/NPZ members without extracting any paths to disk."""
    if depth > ARCHIVE_MAX_DEPTH:
        failures.append({"path": location, "reason": "archive nesting limit exceeded"})
        return
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            seen = set()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                raw = member.filename
                normalized = raw.replace("\\", "/")
                part = PurePosixPath(normalized)
                member_location = f"{location}!/{raw}"
                if (not normalized or normalized.startswith("/") or
                    normalized.startswith("//") or any(x == ".." for x in part.parts) or
                    re.match(r"^[A-Za-z]:", normalized)):
                    failures.append({"path": member_location, "reason": "unsafe archive entry"})
                    continue
                if normalized in seen:
                    failures.append({"path": member_location, "reason": "duplicate archive entry"})
                    continue
                seen.add(normalized)
                if stat.S_ISLNK(member.external_attr >> 16):
                    failures.append({"path": member_location, "reason": "symlink in archive"})
                    continue
                if member.flag_bits & 1:
                    failures.append({"path": member_location, "reason": "encrypted archive member"})
                    continue
                if member.file_size > ARCHIVE_MAX_MEMBER or budget[0] + member.file_size > ARCHIVE_MAX_TOTAL:
                    failures.append({"path": member_location, "reason": "archive size limit exceeded"})
                    return
                # Read and verify CRC rather than trusting ZIP directory metadata.
                with archive.open(member) as stream:
                    blob = stream.read(ARCHIVE_MAX_MEMBER + 1)
                if len(blob) != member.file_size:
                    failures.append({"path": member_location, "reason": "archive member size mismatch"})
                    continue
                budget[0] += len(blob)
                suffix = part.suffix.lower()
                if suffix in ARCHIVE_SUFFIXES:
                    scan_archive_bytes(blob, member_location, failures, budget, depth + 1)
                elif suffix in TEXT_SUFFIXES or part.name.startswith(("LICENSE", "NOTICE")):
                    content = blob.decode("utf-8", errors="replace")
                    for label, pattern in PRIVATE.items():
                        for match in pattern.finditer(content):
                            failures.append({"path": member_location, "reason": label,
                                             "line": content.count("\n", 0, match.start()) + 1})
    except (zipfile.BadZipFile, EOFError, ValueError, RuntimeError, OSError, zlib.error):
        failures.append({"path": location, "reason": "corrupt or unreadable nested archive"})


def strict_tree_failures(root, delivered):
    """Fail closed on unreviewed files in a freshly exported public source tree."""
    issues = []
    for path in root.rglob("*"):
        if not path.is_file() and not path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in LOCAL_ONLY or part.endswith(".egg-info") for part in rel.parts):
            continue
        if rel.suffix in (".pyc", ".pyo"):
            continue
        name = rel.as_posix()
        if name not in delivered:
            issues.append({"path": name, "reason": "unlisted public tree file"})
    return issues


def check(root, *, strict_tree=False):
    root = root.resolve()
    files = public_files(root)
    delivered = {p.relative_to(root).as_posix() for p in files}
    failures, external, links = [], set(), []
    archive_budget = [0]
    if strict_tree:
        failures.extend(strict_tree_failures(root, delivered))
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            failures.append({'path': rel, 'reason': 'symlink in public tree'})
            continue
        if path.stat().st_size > 25 * 1024 * 1024:
            failures.append({'path': rel, 'reason': 'file exceeds public Git budget (25 MiB)'})
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            if path.stat().st_size > ARCHIVE_MAX_MEMBER:
                failures.append({'path': rel, 'reason': 'archive compressed size limit exceeded'})
            else:
                scan_archive_bytes(path.read_bytes(), rel, failures, archive_budget)
        try:
            content = path.read_text()
        except (UnicodeError, ValueError):
            continue
        for label, pattern in PRIVATE.items():
            for match in pattern.finditer(content):
                # Report locations only, never print a detected credential.
                failures.append({'path': rel, 'reason': label, 'line': content.count('\n', 0, match.start()) + 1})
        if path.suffix not in ('.md', '.html'):
            if path.name == 'CITATION.cff':
                external.update(re.findall(r'https?://[^\s<>"\]]+', content))
            continue
        external.update(url.rstrip('.,;') for url in re.findall(r'https?://[^\s<>"\]\)]+', content)
                        if urlsplit(url).hostname not in ('127.0.0.1', 'localhost')
                        and not (urlsplit(url).hostname or '').endswith('.invalid'))
        urls = [m.group(1).strip('<>') for m in MARKDOWN_LINK.finditer(content)]
        parsed = Links()
        parsed.feed(content)
        urls.extend(parsed.links)
        for url in urls:
            parts = urlsplit(url)
            if parts.scheme in ('https', 'http'):
                if parts.hostname not in ('127.0.0.1', 'localhost'):
                    external.add(url)
                continue
            if parts.scheme or parts.netloc:
                failures.append({'path': rel, 'target': url, 'reason': 'unsupported URL scheme'})
                continue
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            good = target.is_relative_to(root) and target.is_file() and target.relative_to(root).as_posix() in delivered
            if good and parts.fragment and target.suffix in ('.md', '.html'):
                good = unquote(parts.fragment) in anchors(target)
            entry = {'path': rel, 'target': url, 'status': 'pass' if good else 'fail'}
            links.append(entry)
            if not good:
                failures.append({**entry, 'reason': 'missing/undelivered file or anchor'})
    demo = root / 'docs/demo/assets.json'
    checked_assets = 0
    workflow = demo.parent / 'workflow/assets.json'
    if not demo.exists():
        failures.append({'path': 'docs/demo/assets.json', 'reason': 'public demo manifest missing'})
    for manifest in (demo, workflow):
        if not manifest.exists() and not (manifest == workflow and workflow.parent.exists()):
            continue
        if not manifest.is_file() or manifest.is_symlink():
            failures.append({'path': manifest.relative_to(root).as_posix(), 'reason': 'public demo manifest missing or unsafe'})
            continue
        for name, meta in json.loads(manifest.read_text())['files'].items():
            p = manifest.parent / name
            rel = (manifest.parent.relative_to(root) / name).as_posix()
            if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(manifest.parent):
                failures.append({'path': rel, 'reason': 'missing/unsafe demo asset'})
                continue
            with p.open('rb') as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            if sha != meta['sha256'] or p.stat().st_size != meta['bytes']:
                failures.append({'path': rel, 'reason': 'demo size/hash mismatch'})
            checked_assets += 1
    return {'status': 'pass' if not failures else 'fail', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'public_files': len(files), 'public_bytes': sum(p.stat().st_size for p in files),
            'relative_links': links, 'external_urls': sorted(external), 'demo_assets_checked': checked_assets,
            'failures': failures, 'network_used': False,
            'nested_archive_bytes_inspected': archive_budget[0], 'strict_tree': strict_tree}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--strict-tree', action='store_true',
                        help='Reject extra files in an exported public source tree (not a dev checkout)')
    args = parser.parse_args()
    result = check(args.root, strict_tree=args.strict_tree)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('relative_links', 'external_urls')}, indent=2))
    raise SystemExit(0 if result['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
