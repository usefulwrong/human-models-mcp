"""Install the optional BodyParts3D 4.3 Anatomy Lab from pinned public sources."""

import argparse
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

import fetch_mirror
import normalize_catalog


SOURCE = Path(__file__).resolve().parent
THREE = (
    "LICENSE", "build/three.core.js", "build/three.module.js",
    "examples/jsm/loaders/GLTFLoader.js", "examples/jsm/controls/OrbitControls.js",
    "examples/jsm/utils/BufferGeometryUtils.js",
)
PACKER = "open-anatomy-atlas-b2488616c5d7b8cb5b03bb9ee86eda911e3b6232"
BUILD = """
const {build43} = require(process.argv[1]);
const [rawDir,listDir,outDir] = process.argv.slice(2);
build43({rawDir,listDir,outDir,mirror:{categories:[]}})
  .catch(error => { console.error(error.message); process.exitCode = 1; });
"""


def write_json(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(data, out, ensure_ascii=False, separators=(",", ":"))
        out.write("\n")


def verify(path, pin):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != pin["bytes"]:
        raise ValueError(f"Missing or wrong-size source file: {path.name}")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != pin["sha256"]:
            raise ValueError(f"Source SHA-256 mismatch: {path.name}")


def membership(data, expected):
    name = expected["path"]
    with ZipFile(BytesIO(data)) as archive:
        if archive.namelist() != [name] or archive.getinfo(name).file_size != expected["bytes"]:
            raise ValueError("Unexpected membership archive shape")
        text = archive.read(name)
    if hashlib.sha256(text).hexdigest() != expected["sha256"]:
        raise ValueError("Versioned membership contents changed")
    return text


def provision_sources(upstream, pins, offline):
    receipt = []
    for name, pin in pins.items():
        path = upstream / name
        status = "verified_cache"
        if path.is_symlink():
            raise ValueError(f"Source file is a symlink: {name}")
        limit = pin.get("max_bytes", pin["bytes"])
        download = not path.exists() and not offline
        if download:
            with urlopen(pin["url"], timeout=45) as response:
                data = response.read(limit + 1)
            status = "downloaded"
        else:
            with path.open("rb") as stream:
                data = stream.read(limit + 1)
        sha = hashlib.sha256(data).hexdigest()
        if len(data) > limit:
            raise ValueError(f"Upstream response exceeds the byte limit: {name}")
        if "membership" in pin:
            # The CGI ZIP timestamp varies between requests. Pin the exact member bytes.
            text = membership(data, pin["membership"])
            target = path.with_suffix(".txt")
            if target.is_symlink() or (target.exists() and target.read_bytes() != text):
                raise ValueError(f"Unverified extracted membership: {target.name}")
            if not target.exists():
                with target.open("xb") as stream:
                    stream.write(text)
        elif len(data) != pin["bytes"] or sha != pin["sha256"]:
            raise ValueError(f"Upstream bytes changed for {name}; review the data pin")
        if download:
            with path.open("xb") as stream:
                stream.write(data)
        receipt.append({"file": name, "status": status, **pin, "observed_sha256": sha, "observed_bytes": len(data)})
    return receipt


def obj_claims(path, fj_id):
    with path.open("rb") as stream:
        prefix = stream.read(1024)
    fields = {}
    for label, pattern, key in (
        (b"File ID", rb"FJ[0-9]{1,8}M?", "obj_fj_id"),
        (b"Concept ID", rb"FMA[1-9][0-9]{0,8}", "obj_concept_id"),
        (b"Representation ID", rb"BP[0-9]{1,12}", "obj_representation_id"),
    ):
        match = re.search(rb"(?m)^# " + label + rb"[^\S\r\n]*:[^\S\r\n]*(" + pattern + rb")\r?$", prefix)
        if match:
            fields[key] = match[1].decode("ascii")
    if fields.pop("obj_fj_id", None) != fj_id:
        raise ValueError(f"Verified OBJ has an unexpected file identity: {fj_id}")
    return fields


def provision(root, cache, offline, *, cache_only=False):
    pins = json.loads((SOURCE / "sources.lock.json").read_text(encoding="utf-8"))
    upstream = cache / "upstream"
    meshes = cache / "meshes"
    upstream.mkdir(parents=True, exist_ok=True)
    print("BodyParts3D © DBCLS. Source geometry CC BY-SA 2.1 Japan. DBCLS archive TSV CC BY 4.0.", flush=True)
    for terms in dict.fromkeys(pin["terms_url"] for pin in pins.values()):
        print(terms, flush=True)
    receipt = provision_sources(upstream, pins, offline)
    fetch_mirror.install(upstream, meshes, offline=offline)

    if cache_only:
        return
    catalog, _ = normalize_catalog.build(upstream)
    with TemporaryDirectory(prefix=".anatomy-lab-", dir=root.parent) as work:
        temporary = Path(work)
        data = temporary / "install"
        data.mkdir()
        shutil.copytree(SOURCE / "site", data / "site")
        (data / "meshes").mkdir()
        for row in catalog["meshes"]:
            name = row["filename"]
            shutil.copyfile(meshes / name, data / "meshes" / name)
            row.update(obj_claims(data / "meshes" / name, row["fj_id"]))
        write_json(data / "catalog.json", catalog)
        with tarfile.open(upstream / "three-0.180.0.tgz") as archive:
            for part in THREE:
                path = data / "site/npm/node_modules/three" / part
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile("package/" + part) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)
        with tarfile.open(upstream / "open-atlas.tar.gz") as archive:
            archive.extractall(temporary, members=(
                info for info in archive.getmembers() if info.name.startswith(PACKER + "/src/")
            ), filter="data")
        meta = temporary / "metadata"
        meta.mkdir()
        for raw, name in (("mirror-FMA2Obj.txt", "FMA2Obj.txt"), ("mirror-obj2FMA.html", "obj2FMA.html")):
            shutil.copyfile(upstream / raw, meta / name)
        if os.name == "nt":
            shutil.copytree(data / "meshes", temporary / "objs")
        else:
            (temporary / "objs").symlink_to(data / "meshes", target_is_directory=True)
        subprocess.run([os.environ.get("HMM_NODE_BIN", "node"), "-e", BUILD, str(temporary / PACKER / "src/data/bp3d43.js"),
                        str(temporary), str(upstream), str(data / "build")], check=True)
        site = data / "site/full/site"
        site.mkdir(parents=True)
        write_json(site / "assets.json", {
            "dataset": "BodyParts3D 4.3", "source_pin": normalize_catalog.PIN,
            "license": "CC-BY-SA-2.1-JP", "attribution": "BodyParts3D © DBCLS",
            "files": {row["fj_id"]: {
                "fma": f"FMA{row['fma_id']}", "bp": row["bp_id"], "name": row["label"],
                "sha256": row["sha256"], "identity_status": row["identity_status"],
            } for row in catalog["meshes"]},
        })
        subprocess.run([sys.executable, str(SOURCE / "pack_glb.py"), str(data)], check=True)
        generated_glb = site / "atlas.glb"
        subprocess.run([sys.executable, str(SOURCE / "pack_scene_assets.py"), "--glb", str(generated_glb)], check=True)
        generated_glb.unlink()
        shutil.rmtree(data / "build")
        write_json(data / "source-receipt.json", {"created_at": datetime.now(UTC).isoformat(),
                   "source_files": receipt, "bodyparts3d_objects_verified": len(catalog["meshes"]),
                   "metadata_scope": "operator-local; redistribution rights unconfirmed"})
        shutil.copyfile(upstream / "mirror-LICENSE", data / "BodyParts3D-LICENSE")
        data.rename(root)
    print(f"Installed {len(catalog['meshes'])} objects in {root}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("destination", type=Path)
    p.add_argument("--cache", type=Path)
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--offline", action="store_true", help="Require all source bytes in the specified cache")
    args = p.parse_args()
    root = args.destination.resolve()
    if not args.cache_only and (args.destination.is_symlink() or args.destination.is_junction() or root.exists()):
        p.error("destination must be new")
    root.parent.mkdir(parents=True, exist_ok=True)
    cache = args.cache.resolve() if args.cache else root.with_name(root.name + "-sources")
    if cache == root or cache.is_relative_to(root):
        p.error("source cache must be outside the installation")
    if os.name == "nt" and not args.offline:
        import truststore
        truststore.inject_into_ssl()
    provision(root, cache, args.offline, cache_only=args.cache_only)


if __name__ == "__main__":
    main()
