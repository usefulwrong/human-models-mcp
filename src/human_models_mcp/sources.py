"""Offline source excerpts and exact model identifiers; no generated anatomy."""

import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET

from .registry import discover, home
from .results import error


def search_sources(query: str, limit: int = 5) -> dict:
    if not isinstance(query, str) or not 1 <= len(query) <= 200 or type(limit) is not int or not 1 <= limit <= 10:
        return error("invalid_input", "query must be 1–200 characters; limit an integer from 1 to 10")
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not tokens or len(tokens) > 20:
        return error("invalid_input", "query must contain 1–20 words or model identifier components")
    root = home()
    lock = json.loads((root / "models.lock.json").read_text())
    locked = {item["path"]: item for item in lock["files"]}
    records = []

    def add(identifier, content, source, version, digest, license_name, kind):
        records.append({"id": identifier, "text": content, "source_url": source, "version": version,
                        "source_sha256": digest, "license": license_name, "evidence_type": kind})

    def asset(relative):
        path = root / "models" / relative
        if relative not in locked or path.is_symlink() or not path.is_file():
            raise ValueError("indexed model source is missing or untrusted")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != locked[relative]["sha256"]:
            raise ValueError("indexed model source hash mismatch")
        url = "https://github.com/google-deepmind/mujoco_menagerie/blob/" + lock["revision"] + "/" + relative
        return data, digest, url

    try:
        data, digest, url = asset("ms_human_700/README.md")
        add("model_manual", data.decode(), url, lock["revision"], digest, lock["license"], "upstream_manual")
        data, digest, url = asset("ms_human_700/MS-Human-700.xml")
        body_sources = ["ms_human_700/MS-Human-700.xml"] + sorted(
            name for name in locked if name.startswith("ms_human_700/assets/body_primary/") and name.endswith(".xml"))
        for relative in body_sources:
            body_data, body_digest, body_url = asset(relative)
            for joint in ET.fromstring(body_data).findall(".//body/joint"):
                name = joint.attrib["name"]
                add(name, f"Joint coordinate identifier {name}; declared type {joint.get('type', 'hinge')}; primary MS-Human-700.",
                    body_url, lock["revision"], body_digest, lock["license"], "upstream_joint_identifier")
        for include in ET.fromstring(data).findall("include"):
            relative = include.attrib["file"]
            if not relative.startswith("assets/muscle/"):
                continue
            data, digest, url = asset("ms_human_700/" + relative)
            for actuator in ET.fromstring(data).findall("./actuator/general"):
                name = actuator.attrib["name"]
                tendon = actuator.attrib["tendon"]
                add(name, f"Muscle actuator identifier {name}; tendon {tendon}; primary MS-Human-700.",
                    url, lock["revision"], digest, lock["license"], "upstream_model_identifier")
    except (OSError, ValueError, ET.ParseError) as exc:
        return error("not_installed", str(exc))
    for scenario in discover()["scenarios"]:
        text = scenario["title"] + "\n" + scenario["scope"]
        digest = hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest()
        add(scenario["id"], text, "local://scenarios/" + scenario["id"], scenario["version"], digest,
            "MIT", "wrapper_scenario_description")
    reference_folder = root / "benchmarks/nichols2016_wrist"
    if (reference_folder / "reference.json").is_file():
        reference = json.loads((reference_folder / "reference.json").read_text())
        for name, expected in reference["files"].items():
            path = reference_folder / name
            if name not in ("article.xml", "reference.csv") or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return error("integrity_error", "experimental source checksum mismatch")
        add("nichols2016_wrist", "Nichols Bednar Murray 2016 experimental cadaver wrist muscle moment arms, Table 2 nonimpaired means and specimen standard deviations. "
            "FCR FCU ECRB ECRL ECU; neutral extension and ulnar deviation; descriptive comparison only, no clinical validation.",
            reference["url"], reference["doi"], reference["files"]["article.xml"], reference["license"], "published_experimental_aggregate")
    for filename in ("SCIENTIFIC_SCOPE.md", "RESEARCH_NOTES.md"):
        path = root / "docs" / filename
        if path.is_file():
            data = path.read_bytes()
            from . import __version__
            add(filename, data.decode(), "local://docs/" + filename, __version__, hashlib.sha256(data).hexdigest(),
                "MIT", "wrapper_scientific_scope")
    expression = " AND ".join('"' + token + '"*' for token in tokens)
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE VIRTUAL TABLE corpus USING fts5(identifier, content)")
            connection.executemany("INSERT INTO corpus VALUES (?, ?)", [(r["id"], r["text"]) for r in records])
            rows = connection.execute("SELECT rowid, snippet(corpus, 1, '[', ']', ' … ', 40) FROM corpus WHERE corpus MATCH ? ORDER BY rank LIMIT ?",
                                      (expression, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        return error("unavailable", "SQLite FTS5 is required: " + str(exc))
    matches = [{**{k: v for k, v in records[row_id - 1].items() if k != "text"}, "excerpt": excerpt}
               for row_id, excerpt in rows]
    return {"status": "ok", "query": query, "backend": "sqlite_fts5", "offline": True,
            "model_revision": lock["revision"], "indexed_records": len(records), "matches": matches,
            "limitations": "Local source excerpts and identifiers only. No universal atlas, translation, computed anatomy, or medical advice."}
