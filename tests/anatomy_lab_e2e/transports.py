"""Exercise a real Lab HTTP server and a fresh MCP stdio process with the official SDK."""
import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import Client, StdioServerParameters


CASES = {"FMA7088": ("heart", "unknown"), "FMA7309": ("right lung", "right"),
         "FMA7310": ("left lung", "left"), "FMA50801": ("brain", "unknown")}
REPRESENTATION = {"dataset": "BodyParts3D", "mesh_version": "4.3", "membership_version": "4.3+4.3i"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exchange(origin, value, headers=None, path="/api/query"):
    request = Request(origin + path, data=canonical(value), headers={
        "Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, None


def check_sources(cache):
    references = {}
    for version in ("43", "43i"):
        with (cache / "upstream" / f"original-FMA2Obj-{version}.txt").open() as stream:
            for line in stream:
                if line.startswith("#") or not line.strip():
                    continue
                concept, _mapping, ids = line.strip().split("\t")
                if concept in CASES:
                    references.setdefault(concept, {})[version] = set(ids.split("+"))
    return references


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    SDK = importlib.metadata.version("mcp")
    print(json.dumps({"python": sys.version, "mcp": SDK, "origin": args.origin, "transport": "stdio"}, default=str))
    source_fjs = check_sources(args.source_cache)
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "lab_mcp"],
                                           env=dict(os.environ)), read_timeout_seconds=40) as client:
        tools = await client.list_tools()
        assert "anatomy_lab" in {tool.name for tool in tools.tools}

        async def compare(operation, **fields):
            start = datetime.now(UTC).isoformat()
            value = {"operation": operation, **fields}
            reply = await client.call_tool("anatomy_lab", {"request": value})
            assert not reply.is_error, str(reply.content)[:500]
            mcp = reply.structured_content
            code, http = exchange(args.origin, value)
            assert code == 200 and canonical(mcp) == canonical(http), operation
            return {"operation": operation, "request": fields, "mcp": mcp, "http": http,
                    "start": start, "end": datetime.now(UTC).isoformat()}

        results = {}
        downloaded = {}
        for fma, (label, side) in CASES.items():
            calls = []
            search_by_name = await compare("anatomy.search", query=label, representation=REPRESENTATION)
            calls.append(search_by_name)
            row, = [row for row in search_by_name["http"]["matches"] if row["id"] == fma]
            assert (row["label"].lower(), row["side"]) == (label, side)
            by_id = await compare("anatomy.search", query=fma, representation=REPRESENTATION)
            assert by_id["http"]["concept"] == row
            calls.append(by_id)
            resolved = {}
            for version, filenames in (("4.3", ("43",)), ("4.3i", ("43i",)), ("4.3+4.3i", ("43", "43i"))):
                representation = {**REPRESENTATION, "membership_version": version}
                members, packs, offset = [], {}, 0
                selection_sha = None
                while offset is not None:
                    page = await compare("anatomy.resolve", concept=fma, representation=representation,
                                         limit=73, offset=offset)
                    calls.append(page)
                    data = page["http"]
                    assert data["status"] == "ok"
                    assert selection_sha is None or selection_sha == data["selection_sha256"]
                    selection_sha = data["selection_sha256"]
                    members.extend(data["members"])
                    packs.update(data["packs"])
                    offset = data["next_offset"]
                ordered = [member["fj_id"] for member in members]
                expected = set.union(*(source_fjs[fma][key] for key in filenames))
                assert len(ordered) == data["counts"]["members"] and ordered == sorted(expected)
                for key in filenames:
                    source = "bp3d_" + key + "_components"
                    assert source_fjs[fma][key] == {m["fj_id"] for m in members if
                                                   source in {p["source_id"] for p in m["memberships"]}}
                    assert len(data["provenance"][source]["sha256"]) == 64
                for name, pack in packs.items():
                    if name not in downloaded:
                        with urlopen(f"{args.origin}/api/pack/{name}/{pack['sha256']}", timeout=30) as response:
                            contents = response.read()
                            assert len(contents) == pack["bytes"] and digest(contents) == pack["sha256"]
                        downloaded[name] = pack
                    assert downloaded[name] == pack
                assert data["pack_bytes"] == sum(p["bytes"] for p in packs.values())
                resolved[version] = {
                    **{k: v for k, v in data.items() if k not in {"members", "packs", "next_offset"}},
                    "ordered_fj_ids": ordered, "ordered_fj_ids_sha256": digest(canonical(ordered)),
                    "rendered_fj_ids": [m["fj_id"] for m in members if m["renderable"]],
                    "packs": dict(sorted(packs.items())), "source_fj_exact_match": True,
                }
            union = resolved["4.3+4.3i"]
            assert row["visual_membership_count"] == union["counts"]["members"]
            created = await compare("scene.create", selection=[], camera={
                "frame": "packed_atlas_m", "position": [0, 1.4, 2], "target": [0, 1, 0], "up": [0, 1, 0],
                "view_asset_sha256": union["source_mesh_inventory_sha256"]})
            selected = await compare("scene.select", scene=created["http"]["scene"],
                                     selection=[fma], representation=REPRESENTATION)
            exported = await compare("scene.export", scene=selected["http"]["scene"])
            assert exported["http"] == selected["http"]
            assert exported["http"]["scene"]["composite"]["selection_sha256"] == union["selection_sha256"]
            calls += [created, selected, exported]
            if args.scene_dir:
                browser_scene = json.loads((args.scene_dir / f"{fma}-desktop.json").read_bytes())
                browser_export = await compare("scene.export", scene=browser_scene)
                assert browser_export["http"]["scene"] == browser_scene
                assert browser_scene["composite"]["selection_sha256"] == union["selection_sha256"]
                calls.append(browser_export)
                union["browser_scene_sha256"] = browser_export["http"]["scene_sha256"]
            (args.output / f"{fma}-http-mcp-full-local.json").write_bytes(canonical(calls) + b"\n")
            summary = [{"operation": c["operation"], "start": c["start"], "end": c["end"],
                        "http_sha256": digest(canonical(c["http"])),
                        "mcp_sha256": digest(canonical(c["mcp"]))} for c in calls]
            results[fma] = {"status": "PASS", "search": row, "versions": resolved, "transport_calls": summary,
                            "http_mcp_exact_match": True, "transport_scene": exported["http"]}
            print(f"{fma}: {len(union['ordered_fj_ids'])} FJ; {union['coverage']}; {len(calls)} exact HTTP/MCP replies")

        negatives = {}
        examples = [
            ("wrong_fma", {"operation": "anatomy.resolve", "concept": "FMA999999999",
                           "representation": REPRESENTATION}, {}, 200, "unknown"),
            ("wrong_version", {"operation": "anatomy.resolve", "concept": "FMA7088",
                               "representation": {**REPRESENTATION, "mesh_version": "4.4"}}, {}, 400, None),
            ("wrong_scene_schema", {"operation": "scene.export", "scene": {"schema_version": "hmm.anatomy.scene/2"}},
             {}, 400, None),
            ("wrong_scene_catalog", {"operation": "scene.export", "scene": {
                **results["FMA7088"]["transport_scene"]["scene"], "atlas_sha256": "0" * 64}}, {}, 200, "unsupported"),
            ("wrong_manifest", {"operation": "scene.export", "scene": {
                **results["FMA7088"]["transport_scene"]["scene"], "composite": {
                    **results["FMA7088"]["transport_scene"]["scene"]["composite"], "asset_manifest_sha256": "0" * 64}}},
             {}, 200, "integrity_error"),
            ("oversized_page", {"operation": "anatomy.resolve", "concept": "FMA7088", "representation": REPRESENTATION,
                                "limit": 201}, {}, 400, None),
            ("oversized_body", {"operation": "anatomy.search", "query": "a" * 66000}, {}, 400, None),
            ("bad_origin", {"operation": "anatomy.search", "query": "heart"}, {"Origin": "https://example.invalid"},
             403, None),
            ("bad_host", {"operation": "anatomy.search", "query": "heart"}, {"Host": "example.invalid"},
             403, None),
        ]
        for name, req, headers, expected, status in examples:
            code, payload = exchange(args.origin, req, headers)
            assert code == expected and (status is None or payload["status"] == status), name
            negatives[name] = {"http_status": code, "response": payload, "status": "PASS"}
        for name, path in (("path_traversal", "/full/site/%2e%2e/%2e%2e/%2e%2e/catalog.json"),
                           ("pack_name", "/api/pack/%2e%2e%2fpack-00.glb/" + "0" * 64),
                           ("pack_hash", "/api/pack/" + next(iter(downloaded)) + "/" + "0" * 64)):
            try:
                urlopen(args.origin + path, timeout=10)
            except HTTPError as exc:
                assert exc.code == 404, (name, exc.code)
                negatives[name] = {"http_status": exc.code, "status": "PASS"}
            else:
                raise AssertionError(name)
        if args.explorer_scene:
            explorer = {}
            for fj in ("FJ3028", "FJ6043", "FJ99999999"):
                explorer[fj] = await compare("anatomy.identify", mesh=fj, representation=REPRESENTATION, limit=5)
            assert explorer["FJ3028"]["http"]["bp_conflict"]
            assert explorer["FJ3028"]["http"]["candidate_count"] > 1
            assert explorer["FJ6043"]["http"]["mesh"]["fma_id"] is None
            assert explorer["FJ99999999"]["http"]["status"] == "unknown"
            for concept, predicate in (("FMA7310", "part_of"), ("FMA5022", "is_a"), ("FMA999999999", "is_a")):
                explorer[concept] = await compare("anatomy.relationships", concept=concept, predicate=predicate,
                                                  direction="in", include_labels=True, limit=2)
            assert explorer["FMA7310"]["http"]["relationships"][0]["related_concept"]["id"]
            assert explorer["FMA5022"]["http"]["relationships"][0]["predicate"] == "is_a"
            assert explorer["FMA999999999"]["http"]["status"] == "unknown"
            document = json.loads(args.explorer_scene.read_bytes())
            explorer["scene"] = await compare("scene.export", scene=document)
            assert explorer["scene"]["http"]["scene"] == document
            (args.output / "explorer-parity.json").write_bytes(canonical(explorer) + b"\n")
            print(f"Explorer: {len(explorer)} additional exact HTTP/MCP replies.")
        output = {"status": "PASS", "cases": results, "security_negatives": negatives, "mcp_sdk": SDK,
                  "unique_packs_verified": len(downloaded)}
        (args.output / "transports.json").write_bytes(canonical(output) + b"\n")
        print(f"Verified {len(downloaded)} unique GLB assets and {len(negatives)} HTTP negatives.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:18943")
    parser.add_argument("--source-cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scene-dir", type=Path)
    parser.add_argument("--explorer-scene", type=Path)
    asyncio.run(run(parser.parse_args()))
