"""Fetch public bytes against the pinned GitHub LFS pointer inventory."""
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from tempfile import NamedTemporaryFile

BATCH_URL = "https://github.com/olivercase/body_parts_3d_api.git/info/lfs/objects/batch"
CHUNK_SIZE = 80
MAX_WORKERS = 6
RATE = 8
STOP = threading.Event()
LOCK = threading.Lock()
NEXT_REQUEST = 0.0


def pinned_inventory(upstream):
    pins = []
    with zipfile.ZipFile(upstream / "mirror-fd527e6.zip") as arc:
        for item in arc.infolist():
            name = pathlib.PurePosixPath(item.filename).name
            match = re.fullmatch(r"(FJ\d+M?)_(BP\d+)_(FMA\d+)_.*\.obj", name)
            if not match:
                continue
            fj, bp, primary_fma = match.groups()
            oid, size = re.fullmatch(
                rb"version https://git-lfs.github.com/spec/v1\noid sha256:([\da-f]{64})\nsize (\d+)\n",
                arc.read(item),
            ).groups()
            pins.append({"fj_id": fj, "filename": f"{fj}.obj", "upstream_path": item.filename.split("/", 1)[1],
                         "source_primary_fma": primary_fma, "size": int(size), "oid": oid.decode()})
    manifest = (upstream / "mirror-FMA2Obj.txt").read_text(encoding="utf-8")
    assert {p["fj_id"] for p in pins} == set(re.findall(r"FJ\d+M?", manifest))
    assert len(pins) == len({p["fj_id"] for p in pins}) == 3210
    return sorted(pins, key=lambda p: p["fj_id"])


def verified(path, pin):
    return not path.is_symlink() and path.is_file() and path.stat().st_size == pin["size"] and hashlib.sha256(path.read_bytes()).hexdigest() == pin["oid"]


def fetch(request, bound):
    global NEXT_REQUEST
    with LOCK:
        now = time.monotonic()
        when = max(now, NEXT_REQUEST)
        NEXT_REQUEST = when + 1 / RATE
    STOP.wait(max(0, when - now))
    if STOP.is_set():
        raise RuntimeError("Stopped after upstream access response")
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:
            data = reply.read(bound + 1)
            if len(data) > bound:
                raise ValueError("Response exceeded pinned byte limit")
            return data
    except urllib.error.HTTPError as err:
        if err.code in {401, 403, 429}:
            STOP.set()
        raise


def download(pin, answer, meshes):
    dst = meshes / pin["filename"]
    if verified(dst, pin):
        return {"fj_id": pin["fj_id"], "status": "verified_cache"}
    if dst.exists() or dst.is_symlink():
        raise ValueError("Permanently installed OBJ failed its source pin: " + dst.name)
    try:
        action = answer["actions"]["download"]
        if not action["href"].startswith("https://"):
            raise ValueError("Non-HTTPS LFS object URL")
        data = fetch(urllib.request.Request(action["href"], headers=action.get("header", {})), pin["size"])
        if len(data) != pin["size"] or hashlib.sha256(data).hexdigest() != pin["oid"]:
            raise ValueError("Byte length or digest mismatch")
        with NamedTemporaryFile(dir=meshes, prefix=f".{dst.stem}-", suffix=".partial", delete=False) as stream:
            tmp = pathlib.Path(stream.name)
            stream.write(data)
        try:
            dst.hardlink_to(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return {"fj_id": pin["fj_id"], "status": "downloaded"}
    except (OSError, KeyError, RuntimeError, ValueError) as err:
        return {"fj_id": pin["fj_id"], "status": "failed", "error": f"{type(err).__name__}: {err}"}


def install(upstream, meshes, *, offline):
    pins = pinned_inventory(upstream)
    meshes.mkdir(parents=True, exist_ok=True)
    missing = [pin for pin in pins if not verified(meshes / pin["filename"], pin)]
    bad = [pin["filename"] for pin in missing
           if (meshes / pin["filename"]).exists() or (meshes / pin["filename"]).is_symlink()]
    if bad:
        raise ValueError("Existing source objects failed their pins: " + ", ".join(bad[:6]))
    if not missing:
        print(f"Verified {len(pins)} local OBJ files")
        return
    if offline:
        raise ValueError(f"Offline cache is missing {len(missing)} pinned source objects")
    (upstream / "lfs-chunks").mkdir(exist_ok=True)
    failures = 0
    started = datetime.datetime.now(datetime.UTC).isoformat()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for start in range(0, len(missing), CHUNK_SIZE):
            if STOP.is_set():
                break
            chunk = missing[start : start + CHUNK_SIZE]
            pending = {p["oid"]: p for p in chunk}
            if pending:
                payload = json.dumps({"operation": "download", "transfers": ["basic"], "objects": [
                    {"oid": p["oid"], "size": p["size"]} for p in pending.values()
                ]}).encode()
                media_type = "application/vnd.git-lfs+json"
                request = urllib.request.Request(BATCH_URL, data=payload, headers={
                    "Accept": media_type, "Content-Type": media_type,
                })
                try:
                    raw = fetch(request, 2_000_000)
                    answers = {r["oid"]: r for r in json.loads(raw)["objects"]}
                except (OSError, RuntimeError, ValueError, KeyError) as err:
                    raise ValueError(f"LFS batch failed at source offset {start}: {type(err).__name__}") from err
                if any(a.get("error", {}).get("code") in {401, 403, 429} for a in answers.values()):
                    STOP.set()
                results = list(pool.map(lambda p: download(p, answers.get(p["oid"], {}), meshes), chunk))
            else:
                results = [{"fj_id": p["fj_id"], "status": "verified_cache"} for p in chunk]
            receipt = {"at": datetime.datetime.now(datetime.UTC).isoformat(), "started": started,
                       "batch_url": BATCH_URL, "ordered_pin_set_sha256": hashlib.sha256(json.dumps(chunk, sort_keys=True).encode()).hexdigest(),
                       "results": [{**p, **r} for p, r in zip(chunk, results, strict=True)]}
            out = upstream / "lfs-chunks" / f"{start:04d}-{os.getpid()}.json"
            out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
            chunk_failures = sum(r["status"] == "failed" for r in results)
            failures += chunk_failures
            print(datetime.datetime.now(datetime.UTC).isoformat(), start + len(chunk), "/", len(missing), "failed:", failures, "receipt:", out, flush=True)
    if failures or STOP.is_set():
        raise ValueError("Mesh download is incomplete. Verified objects are retained in the cache.")
