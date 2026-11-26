"""Attach independently sourced graph records to a new local atlas catalog."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from anatomy_lab import MAX_CATALOG_BYTES, read_bounded
from provision import verify


UW_CAPTURE = ("https://web.archive.org/web/20160412160129id_/http://sig.biostr.washington.edu/"
              "share/downloads/fma/FMA_Release/alt/v3.2.1/owl_file/fma_3.2.1_owl_file.zip")
UW = {"bytes": 14_945_883, "sha256": "704067f020a68727ec241d94cae54a4eaffbfd99135a8128551595f1798d1775"}
OWL_SHA = "b04c6662862bf8e2bd51d3600ec65ddf9b8e3121336765d902e3a23a3e3e5bda"
SAMPLE = {"bytes": 68_616, "sha256": "17f942a9076a2fc1e7ba0a5787b143eda3460f3b92442efbd1fa9c97aa5510ac"}
FMA = "http://purl.org/sig/fma/"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
PARTS = {"part_of", "constitutional_part_of", "regional_part_of", "systemic_part_of"}
WHOLES = {"has_part", "constitutional_part", "regional_part", "systemic_part"}
PREDICATES = {RDFS + "subClassOf": "is_a", **{"{" + FMA + "}" + key: key for key in PARTS | WHOLES}}


def read_owl(archive_path, selected):
    verify(archive_path, UW)
    with ZipFile(archive_path) as archive:
        member = archive.getinfo("fma3.2.owl")
        if member.file_size != 200_423_867:
            raise ValueError("Unexpected FMA 3.2.1 OWL length")
        with archive.open(member) as data:
            if hashlib.file_digest(data, "sha256").hexdigest() != OWL_SHA:
                raise ValueError("Unexpected FMA 3.2.1 OWL digest")
        with archive.open(member) as data:
            nodes, candidates = {}, []
            parser = iter(ET.iterparse(data, events=("start", "end")))
            _, root = next(parser)
            if root.tag != RDF + "RDF":
                raise ValueError("Unexpected FMA RDF container")
            depth = 1
            for event, entity in parser:
                if event == "start":
                    depth += 1
                    continue
                depth -= 1
                if depth != 1:
                    continue
                name = entity.get(RDF + "about", "")
                number = entity.findtext("{" + FMA + "}FMAID", "").strip()
                if name.startswith(FMA) and re.fullmatch(r"[0-9]+", number) and int(number) in selected:
                    identifier = int(number)
                    nodes[name] = identifier
                    for prop in entity:
                        target = prop.get(RDF + "resource")
                        if target and target.startswith(FMA) and prop.tag in PREDICATES:
                            candidates.append((identifier, PREDICATES[prop.tag], target))
                root.clear()
    return sorted({(s, p, nodes[o]) for s, p, o in candidates if o in nodes})


def add_source(catalog, source):
    if any(row["id"] == source["id"] for row in catalog["sources"]):
        raise ValueError(f"Graph source already installed: {source['id']}")
    catalog["sources"].append(source)


def add_owl(catalog, path, known):
    name = "uw_fma_321_archive"
    rows = read_owl(path, known)
    add_source(catalog, {"id": name, "version": "FMA 3.2.1 OWL-Full", "url": UW_CAPTURE,
                         "sha256": UW["sha256"], "license": "CC-BY-3.0",
                         "license_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC3944952/",
                         "attribution": "Foundational Model of Anatomy, University of Washington",
                         "coverage": "named asserted relations between installed concepts"})
    catalog["relations"].extend({
        "subject_fma": s, "predicate": "part_of" if p in PARTS else "has_part" if p in WHOLES else p,
        "source_predicate": p, "object_fma": o, "source_id": name, "inferred": False,
    } for s, p, o in rows)
    catalog["manifest"]["historical_fma321_installed_edges"] = len(rows)


def add_sample(catalog, path, known):
    verify(path, SAMPLE)
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = {}
    for row in data["relations"]:
        version = row["version"]
        parent = row["object_fma"]
        source_id = f"bp3d_{version.replace('.', '')}_direct_fma{parent}"
        source = {"id": source_id, "version": version, "tree_version": row["tree_version"],
                  "url": row["source_url"], "sha256": row["source_sha256"],
                  "license": "REDISTRIBUTION_UNCONFIRMED",
                  "scope": "sampled direct parent adjacency, authored inference status unspecified"}
        if source_id not in sources:
            add_source(catalog, source)
            sources[source_id] = source
        elif sources[source_id] != source:
            raise ValueError("Inconsistent adjacency source")
        subject = row["subject_fma"]
        for identifier in (subject, parent):
            if identifier not in known:
                catalog["concepts"].append({"fma_id": identifier, "label": f"FMA{identifier}",
                                            "side": "unknown", "source_id": source_id})
                known.add(identifier)
        catalog["relations"].append({"subject_fma": subject, "predicate": row["predicate"], "object_fma": parent,
                                     "source_id": source_id, "inferred": None})
    catalog["manifest"]["direct_43i_sample_rows"] = data["per_build_counts"]["4.3i"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fma321", type=Path, help="Pinned historical UW OWL-Full ZIP")
    parser.add_argument("--direct-sample", type=Path, help="Pinned local Anatomography adjacency sample")
    args = parser.parse_args()
    if not (args.fma321 or args.direct_sample):
        parser.error("select at least one graph source")
    catalog = json.loads(read_bounded(args.catalog, MAX_CATALOG_BYTES))
    known = {int(str(item["fma_id"]).removeprefix("FMA")) for item in catalog["concepts"]}
    if args.fma321:
        add_owl(catalog, args.fma321, known)
    if args.direct_sample:
        add_sample(catalog, args.direct_sample, known)
    with args.output.open("x") as stream:
        json.dump(catalog, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
    print(json.dumps({k:v for k,v in catalog["manifest"].items()
                      if k.endswith(("edges", "rows", "coverage", "edges_received"))}))


if __name__ == "__main__":
    main()
