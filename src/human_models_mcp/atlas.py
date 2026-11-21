"""Optional pinned BodyParts3D visual data. Downloads run only from the local CLI."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from .rendering import digest, queue_root, write_json

LOCK = Path(__file__).with_name("atlas_pectoralis.json")


def atlas_lock():
    return json.loads(LOCK.read_text())


def atlas_lock_digest(lock):
    return hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()


def atlas_cache():
    return queue_root() / ".bodyparts3d"


def verify_asset(path, asset):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != asset["bytes"]:
        raise ValueError("missing or wrong-size pinned atlas object: " + path.name)
    if digest(path) != asset["sha256"]:
        raise ValueError("atlas checksum mismatch: " + path.name)


def provision_atlas(accepted_license, offline=False, source_dir=None):
    """Verify a licensed local cache, import pinned local copies, or download the three reviewed objects."""
    lock = atlas_lock()
    if accepted_license != lock["license"]:
        raise ValueError("explicit acceptance of " + lock["license"] + " required")
    cache = atlas_cache()
    cache.mkdir(exist_ok=True)
    if cache.is_symlink():
        raise ValueError("invalid atlas cache directory")
    for name, asset in lock["files"].items():
        path = cache / name
        if path.exists() or path.is_symlink():
            verify_asset(path, asset)
            continue
        if source_dir is not None:
            local = Path(source_dir) / name
            verify_asset(local, asset)
            data = local.read_bytes()
        elif offline:
            raise ValueError("offline atlas cache miss: " + name)
        else:
            with urlopen(asset["url"], timeout=30) as response:
                data = response.read(asset["bytes"] + 1)
        if len(data) != asset["bytes"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("atlas source differs from pinned bytes: " + name)
        # Exclusive creation avoids overwriting older evidence or a symlink.
        with path.open("xb") as stream:
            stream.write(data)
    write_json(cache / "license_receipt.json", {"license": accepted_license, "atlas_lock_sha256": atlas_lock_digest(lock)})
    return lock


def atlas_inputs():
    lock = atlas_lock()
    cache = atlas_cache()
    if cache.is_symlink():
        raise ValueError("invalid atlas cache directory")
    receipt = cache / "license_receipt.json"
    if (receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 1024
            or json.loads(receipt.read_text()) != {"license": lock["license"], "atlas_lock_sha256": atlas_lock_digest(lock)}):
        raise ValueError("atlas license receipt missing or no longer matches the pin; use provision-atlas")
    for name, asset in lock["files"].items():
        verify_asset(cache / name, asset)
    return lock
