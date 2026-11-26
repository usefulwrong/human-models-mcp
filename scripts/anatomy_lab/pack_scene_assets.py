"""Partition an existing GLB by preset demand and locality. Copy each FJ primitive verbatim."""
import argparse
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--glb", type=Path, required=True)
parser.add_argument("--scenes", type=Path)
parser.add_argument("--out", type=Path)
args = parser.parse_args()
GLB = args.glb
OUT = args.out or GLB.parent / "packs"
OUT.mkdir()
with GLB.open("rb") as stream:
    magic, version, size, json_bytes, json_tag = struct.unpack("<4sIIII",stream.read(20))
    assert (magic,version,size,json_tag) == (b"glTF",2,GLB.stat().st_size,0x4E4F534A)
    source = json.loads(stream.read(json_bytes))
    binary_bytes, binary_tag = struct.unpack("<II",stream.read(8))
    assert binary_tag == 0x004E4942
    binary = stream.read(binary_bytes)
    assert not stream.read(1)
metadata = json.loads((args.scenes or GLB.parent / "scenes.json").read_text(encoding="utf-8"))
presets = {k: set(s["visible_parts"]) for k,s in metadata["scenes"].items() if "visible_parts" in s}
groups = defaultdict(list)
for node in source["nodes"]:
    groups[tuple(k for k,v in presets.items() if node["name"] in v)].append(node)
manifest = {"format":"hmm-glb-packs/2","source_sha256":metadata["source_sha256"],"packs":{}}
PACK_TARGET = 4 * 1024 * 1024


def node_bytes(node):
    primitive = source["meshes"][node["mesh"]]["primitives"][0]
    return 1400 + sum(source["bufferViews"][source["accessors"][aid]["bufferView"]]["byteLength"]
                      for aid in (*primitive["attributes"].values(), primitive["indices"]))


def locality(node):
    part = metadata["parts"][node["name"]]
    x, y, z, right, top, front = part["bbox"]
    return part["layer"], (y + top) // .4, (x + right) // .3, (z + front) // .3, node["name"]


def partitions(nodes):
    if sum(map(node_bytes, nodes)) <= PACK_TARGET:
        yield nodes
        return
    chunk, size = [], 0
    for node in sorted(nodes, key=locality):
        weight = node_bytes(node)
        if chunk and size + weight > PACK_TARGET:
            yield chunk
            chunk, size = [], 0
        chunk.append(node)
        size += weight
    if chunk:
        yield chunk


files = {}
for i, (signature, nodes) in enumerate(groups.items()):
    chunks = list(partitions(nodes))
    for j, chunk in enumerate(chunks):
        suffix = f"-{j:02d}" if len(chunks) > 1 else ""
        files[f"pack-{i:02d}{suffix}.glb"] = signature, chunk

max_bytes = 0
for name, (signature, nodes) in files.items():
    pack = {key:[] for key in ("nodes","meshes","materials","bufferViews","accessors")}
    body=bytearray()
    part_hashes = {}

    def copy_accessor(aid):
        accession = source["accessors"][aid].copy()
        view = source["bufferViews"][accession["bufferView"]].copy()
        assert view["buffer"] == 0
        offset = view.get("byteOffset",0)
        data = binary[offset:offset+view["byteLength"]]
        assert len(data)==view["byteLength"]
        view["byteOffset"] = len(body)
        body.extend(data)
        body.extend(bytes(-len(body)%4))
        accession["bufferView"] = len(pack["bufferViews"])
        pack["bufferViews"].append(view)
        pack["accessors"].append(accession)
        return len(pack["accessors"])-1, hashlib.sha256(data).hexdigest()

    for node in nodes:
        mesh = source["meshes"][node["mesh"]]
        assert len(mesh["primitives"])==1
        item = mesh["primitives"][0].copy()
        item["attributes"] = item["attributes"].copy()
        receipt = {}
        for attr, aid in item["attributes"].items():
            item["attributes"][attr], receipt[attr] = copy_accessor(aid)
        item["indices"], receipt["indices"] = copy_accessor(item["indices"])
        mat=source["materials"][item["material"]]
        part_hashes[node["name"]] = {"buffers":receipt,"material_sha256":hashlib.sha256(
            json.dumps(mat,sort_keys=True,separators=(",",":")).encode()).hexdigest()}
        item["material"] = len(pack["materials"])
        pack["materials"].append(mat)
        pack["nodes"].append(dict(node,mesh=len(pack["meshes"])))
        pack["meshes"].append(dict(mesh,primitives=[item]))
    pack.update(asset=source["asset"],scene=0,scenes=[{"nodes":list(range(len(nodes)))}],
                buffers=[{"byteLength":len(body)}])
    header=json.dumps(pack,separators=(",",":")).encode()
    header+=b" "*(-len(header)%4)
    target=OUT / name
    with target.open("xb") as stream:
        stream.write(struct.pack("<4sIIII",b"glTF",2,28+len(header)+len(body),len(header),0x4E4F534A))
        stream.write(header)
        stream.write(struct.pack("<II",len(body),0x004E4942))
        stream.write(body)
    raw=target.read_bytes()
    bin_offset = 28+len(header)
    parsed=json.loads(raw[20:20+len(header)])
    file_buf=memoryview(raw)[bin_offset:]
    for node in parsed["nodes"]:
        item=parsed["meshes"][node["mesh"]]["primitives"][0]
        for attr,aid in dict(item["attributes"],indices=item["indices"]).items():
            access=parsed["accessors"][aid]
            view=parsed["bufferViews"][access["bufferView"]]
            data=file_buf[view["byteOffset"]:view["byteOffset"]+view["byteLength"]]
            assert hashlib.sha256(data).hexdigest()==part_hashes[node["name"]]["buffers"][attr]
        material=parsed["materials"][item["material"]]
        assert hashlib.sha256(json.dumps(material,sort_keys=True,separators=(",",":")).encode()).hexdigest()==part_hashes[node["name"]]["material_sha256"]
    max_bytes += len(raw)
    manifest["packs"][name]={"presets":list(signature),"parts":list(part_hashes),
                             "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}

assert {n for v in manifest["packs"].values() for n in v["parts"]} == metadata["parts"].keys()
assert sum(len(v["parts"]) for v in manifest["packs"].values()) == len(metadata["parts"])
manifest["original_glb_sha256"]=hashlib.sha256(GLB.read_bytes()).hexdigest()
(OUT/"manifest.json").write_text(json.dumps(manifest,sort_keys=True,separators=(",",":"))+"\n", encoding="utf-8", newline="\n")
print(f"{len(files)} packs, {max_bytes} total bytes")
for name,ids in presets.items():
    loaded = [x for x in manifest["packs"].values() if name in x["presets"]]
    assert {y for x in loaded for y in x["parts"]} == ids
    print(f"{name:<18} {len(loaded):>2} files, {sum(x['bytes'] for x in loaded):>9} bytes, {len(ids):>4} FJs")
