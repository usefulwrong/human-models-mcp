"""Preserve packed display triangle identity and convert to standard glTF binary."""
import hashlib
import json
import pathlib
import re
import struct
import sys

import numpy as np

target = pathlib.Path(sys.argv[1])
packed = target / "build"
site = target / "site/full/site"
catalog = json.loads((target / "catalog.json").read_text(encoding="utf-8"))
index = json.loads((packed / "index.json").read_text(encoding="utf-8"))
receipt = json.loads((site / "assets.json").read_text(encoding="utf-8"))
source_ids = sorted(receipt["files"])
digest = hashlib.sha256(json.dumps({k: receipt["files"][k]["sha256"] for k in source_ids},
                                   sort_keys=True, separators=(",",":")).encode()).hexdigest()
bin_data = (packed / "meshes.bin").read_bytes()


def arr(name, dtype):
    offset, size = index["buffers"][name]
    return np.frombuffer(bin_data[offset:offset+size], dtype)


positions = arr("positions", "<f4").reshape(-1, 3)
normals = arr("normals", "<i2")[:positions.size].reshape(-1, 3)
tri = arr("indices", "<u4")
nodes, meshes, materials, views, accessors = [], [], [], [], []
payload = bytearray()


def add_data(data, type_, gl_type, mode, bounds=False):
    accessors.append({"bufferView": len(views), "componentType": gl_type, "count": len(data), "type": type_})
    if bounds:
        accessors[-1].update(min=data.min(axis=0).tolist(), max=data.max(axis=0).tolist())
    views.append({"buffer": 0, "byteOffset": len(payload), "byteLength": data.nbytes, "target": mode})
    payload.extend(data.tobytes())
    return len(accessors) - 1


def fmt(vector):
    return [round(x, 9) for x in vector]


def render_color(key, layer):
    hashed = 2166136261
    for c in key:
        hashed = ((hashed ^ ord(c)) * 16777619) & 0xffffffff
    spread = 0.06 if layer in {"artery", "vein", "nervous"} else 0.13
    factor = 1 - spread + 2 * spread * hashed / 4294967295
    return [min(1, x * factor) for x in index["categories"][layer]["color"]]


parts = {}
for e in index["elements"]:
    name, layer = e["k"], e["t"]
    raw = receipt["files"][name]
    if re.search(r"^(right |left )?(clavicle|humerus|scapula)$", raw["name"], re.I):
        layer = "bone"
    inds = tri[e["o"]:e["o"]+e["n"]]
    low, high = int(inds.min()), int(inds.max()) + 1
    points = positions[low:high]
    normal = normals[low:high].astype("<f4") / 32767
    norm = np.linalg.norm(normal, axis=1)
    np.divide(normal, norm[:, None], where=(norm != 0)[:,None], out=normal)
    normal[norm == 0] = [0., 0., 1.]
    local = inds - low
    color = render_color(name, layer)
    materials.append({"name":name,"doubleSided":True,"pbrMetallicRoughness":{
        "baseColorFactor":[*color,1], "metallicFactor":0,"roughnessFactor":1}})
    meshes.append({"primitives":[{"attributes":{"POSITION":add_data(points,"VEC3",5126,34962,True),
                                                "NORMAL":add_data(normal,"VEC3",5126,34962)},
                                   "indices":add_data(local,"SCALAR",5125,34963),"material":len(materials)-1}]})
    nodes.append({"name":name,"mesh":len(meshes)-1})
    label = raw["name"]
    side = sorted(set(re.findall(r"\b(left|right)\b",label.lower())))
    if raw.get("identity_status") == "DISPUTED":
        label += " [disputed source identity]"
    parts[name] = {"fj":name,"fma":raw["fma"],"bp":raw["bp"],"label":label,"layer":layer,
                   "side":side[0] if len(side) == 1 else "unknown", "color":color,
                   "identity_status":raw.get("identity_status", "MATCH"),
                   "bbox":e["b"],"sha256":raw["sha256"],"triangles":e["n"]//3}

doc = {"asset":{"version":"2.0","generator":"HMM v0.9 viewer bakeoff derived from Open Anatomy Atlas packed data"},
       "scene":0,"scenes":[{"nodes":list(range(len(nodes)))}],"nodes":nodes,"meshes":meshes,
       "materials":materials,"buffers":[{"byteLength":len(payload)}],"bufferViews":views,"accessors":accessors}
gltf = json.dumps(doc,separators=(",",":")).encode()
gltf += b" " * (-len(gltf) % 4)
with (site / "atlas.glb").open("wb") as out:
    out.write(struct.pack("<4sIIII", b"glTF", 2, 28 + len(gltf) + len(payload), len(gltf), 0x4e4f534a))
    out.write(gltf)
    out.write(struct.pack("<II",len(payload),0x004e4942))
    out.write(payload)

all_names = list(parts)
bone = [k for k, r in parts.items() if r["layer"] == "bone"]
muscle = [k for k, r in parts.items() if r["layer"] == "muscle"]
skin = [k for k, r in parts.items() if r["label"].lower() == "skin"]
vessels = [k for k,r in parts.items() if r["layer"] in {"artery", "vein"}]
members = {}
if len(parts) == 3210:
    for r in catalog["components"]:
        if r["source_id"] == "bp3d_43_components" and r["fj_id"] in parts:
            members.setdefault(r["fma_id"], set()).add(r["fj_id"])

shoulder = [k for k, r in parts.items() if r["layer"] in {"bone","muscle","ligament"}
            and re.search(r"clavicle|scapula|humerus|pectoralis|triceps|biceps brachii|brachialis|brachioradialis|deltoid|elbow|rotator",r["label"],re.I)]
heart = members.get(7088,set())
rib_cage = members.get(7480,set())
lung = {k for k,r in parts.items() if "bronchopulmonary segment" in r["label"].lower() and
        "parenchyma" in r["label"].lower()}
brain = members.get(50801,set())
skull = members.get(46565,set())
sagittal = [k for k,r in parts.items() if r["layer"] in {"bone","organ","nervous"}]
cases = [
    ("whole-anterior", skin or all_names, 0), ("whole-posterior", skin or all_names, np.pi),
    ("skeleton", bone, 0), ("muscles", muscle, 0), ("shoulder-elbow", shoulder, 0.22),
    ("heart-chest", heart | rib_cage | lung if heart else [], -.15),
    ("lungs-segments", lung, 0.12), ("vessels", vessels, 0),
    ("head-brain",brain | skull if brain else [], -0.35),("midsagittal",sagittal, np.pi/2),
]
scenes = {}
for key, names, yaw in cases:
    coverage = {"status":"candidate","reason":"Case membership selected from source labels and unmodified display categories"}
    if len(parts) != 3210:
        if key in {"whole-anterior","whole-posterior","head-brain","midsagittal","heart-chest","lungs-segments","vessels"}:
            names = []
        coverage = {"status":"regional_control","reason":"Eight verified right shoulder/arm OBJ files only"}
    if not names:
        scenes[key] = {"coverage":{"status":"unsupported","reason":"Required source meshes are not installed"}}
        continue
    names = sorted(names)
    boxes = np.asarray([parts[k]["bbox"] for k in names])
    lo, hi = boxes[:,:3].min(axis=0), boxes[:,3:].max(axis=0)
    target = (lo+hi)/2
    dist = max(0.02,float(np.linalg.norm(hi-lo))*1.6)
    opaque = sorted(heart if key == "heart-chest" else brain if key == "head-brain" else set())
    pitch = .07 if key != "midsagittal" else 0
    eye = target + dist*np.asarray([np.sin(yaw)*np.cos(pitch),np.sin(pitch),np.cos(yaw)*np.cos(pitch)])
    scenes[key] = {"format":"hmm-viewer-spike/1","scene":key,"source_sha256":digest,"selection":[],
                   "visible_parts":names,"visible_layers":sorted({parts[k]["layer"] for k in names}),
                   "camera":{"frame":"packed-atlas-m","position":fmt(eye),"target":fmt(target),"up":[0,1,0],"fov_degrees":40},
                   "clip_plane":[1,0,0,0] if key=="midsagittal" else None,
                   "opaque_focus_parts":opaque,"context_opacity":0.1 if opaque else 1.0,"coverage":coverage}

relationships = {}
fma_ids = {r["fma"] for r in parts.values()}
labels = {r["fma_id"]: r["label"] for r in catalog["concepts"]}
for edge in catalog["relations"]:
    subject = f"FMA{edge['subject_fma']}"
    if subject in fma_ids and edge["source_id"] in ("bp3d_archive_isa_edges", "bp3d_archive_partof_edges"):
        object_id = edge["object_fma"]
        kind = edge["predicate"].upper().replace("_", "-")
        relationships.setdefault(subject, {}).setdefault(kind, []).append(
            {"fma": f"FMA{object_id}", "label": labels[object_id]})
site.joinpath("scenes.json").write_text(json.dumps({"source_sha256":digest,"scenes":scenes,"parts":parts,
    "bbox":index["bbox"],"relationships":relationships,"dataset":receipt["dataset"],"license":receipt["license"],
    "attribution":receipt["attribution"],"source_pin":receipt["source_pin"]},separators=(",",":"))+"\n", encoding="utf-8", newline="\n")
print(json.dumps({"parts":len(parts),"triangles":sum(r["triangles"] for r in parts.values()),
                  "glb_bytes":site.joinpath("atlas.glb").stat().st_size,"source_sha256":digest}))
