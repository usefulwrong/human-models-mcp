"""Build and verify public source and Windows bootstrap ZIPs."""

import argparse
import hashlib
from pathlib import Path, PureWindowsPath
import tempfile
import tomllib
import zipfile

from public_check import ROOT, check, public_files


def digest(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    name = f"human-models-mcp-{version}"
    args.output.mkdir(parents=True, exist_ok=True)
    files = public_files(ROOT)
    checksums = []
    for variant in ("windows-x64", "source"):
        archive = args.output / f"{name}-{variant}.zip"
        prefix = name + ("-windows-x64" if variant == "windows-x64" else "")
        written = set()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for source in files:
                relative = source.relative_to(ROOT)
                key = relative.as_posix()
                if (source.is_symlink() or source.is_junction() or key.casefold() in written
                        or any(PureWindowsPath(part).is_reserved() for part in relative.parts)):
                    raise ValueError(f"unsafe public source file: {key}")
                written.add(key.casefold())
                data = source.read_bytes()
                if source.suffix in {".cmd", ".bat"}:
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                item = zipfile.ZipInfo(f"{prefix}/{key}", (2020, 1, 1, 0, 0, 0))
                item.external_attr = (source.stat().st_mode & 0xFFFF) << 16
                output.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(archive) as packaged:
            packaged.extractall(temporary)
            result = check(Path(temporary) / prefix, strict_tree=True)
            if result["status"] != "pass":
                raise ValueError(result["failures"])
        checksums.append(f"{digest(archive)}  {archive.name}")
        print(f"{archive.name} {archive.stat().st_size} bytes")
    (args.output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
