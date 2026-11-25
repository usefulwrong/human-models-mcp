"""Small GLB writer for static geometry, standard skins, linear TRS and morphs."""

import json
import struct

import numpy as np


TYPES = {5121: "<u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
SHAPES = {"SCALAR": (), "VEC3": (3,), "VEC4": (4,), "MAT4": (16,)}
# World Z-up to glTF Y-up, metres in both.
BASIS = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])
B4 = np.eye(4)
B4[:3, :3] = BASIS


def unpack(raw):
    if len(raw) < 28 or struct.unpack_from("<4sII", raw) != (b"glTF", 2, len(raw)):
        raise ValueError("invalid GLB header")
    size, kind = struct.unpack_from("<I4s", raw, 12)
    if kind != b"JSON" or size % 4 or size > len(raw) - 28:
        raise ValueError("invalid GLB JSON chunk")
    length, kind = struct.unpack_from("<I4s", raw, 20 + size)
    if kind != b"BIN\0" or length != len(raw) - 28 - size:
        raise ValueError("invalid GLB binary chunk")
    return json.loads(raw[20:20 + size]), raw[28 + size:]


def array(doc, blob, idx):
    a = doc["accessors"][idx]
    view = doc["bufferViews"][a["bufferView"]]
    if view.get("byteStride") or a.get("sparse") or a.get("normalized"):
        raise ValueError("unexpected source accessor encoding")
    shape = (a["count"], *SHAPES[a["type"]])
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(blob, TYPES[a["componentType"]], np.prod(shape), start).reshape(shape)


def face_vectors(points, faces):
    first, second, third = np.moveaxis(np.asarray(points)[..., faces, :], -2, 0)
    return np.cross(second - first, third - first)


def normals(points, faces):
    result = np.zeros_like(points, dtype=float)
    vectors = face_vectors(points, faces)
    np.add.at(result, faces.ravel(), np.repeat(vectors, 3, axis=0))
    lengths = np.linalg.norm(result, axis=1, keepdims=True)
    return result / np.maximum(lengths, 1e-20)


class Clip:
    def __init__(self, times):
        self.doc = {"asset": {"version": "2.0", "generator": "Human Models MCP MotionScene"},
                    "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                    "materials": [], "accessors": [], "bufferViews": [], "buffers": [],
                    "animations": [{"name": "Saved MuJoCo states · assisted", "channels": [], "samplers": []}]}
        self.blob = bytearray()
        self.clock = self.accessor(np.array(times) - times[0], "SCALAR", bounds=True)

    def accessor(self, values, kind, component=5126, bounds=False, target=None):
        values = np.asarray(values, dtype=TYPES[component]).reshape((-1, *SHAPES[kind]))
        self.blob.extend(bytes(-len(self.blob) % 4))
        view = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": values.nbytes}
        if target:
            view["target"] = target
        self.blob.extend(values.tobytes())
        a = {"bufferView": len(self.doc["bufferViews"]), "componentType": component,
             "count": len(values), "type": kind}
        if bounds:
            a.update(min=np.atleast_1d(values.min(0)).tolist(), max=np.atleast_1d(values.max(0)).tolist())
        self.doc["bufferViews"].append(view)
        self.doc["accessors"].append(a)
        return len(self.doc["accessors"]) - 1

    def node(self, name, *, root=True, **fields):
        index = len(self.doc["nodes"])
        self.doc["nodes"].append({"name": name, **fields})
        if root:
            self.doc["scenes"][0]["nodes"].append(index)
        return index

    def material(self, name, color, roughness=.62):
        self.doc["materials"].append({"name": name, "doubleSided": True,
                                      "pbrMetallicRoughness": {"baseColorFactor": [*color, 1],
                                                               "roughnessFactor": roughness,
                                                               "metallicFactor": 0}})
        return len(self.doc["materials"]) - 1

    def mesh(self, name, layer, points, faces, material, weights=None, joints=None, **identity):
        attributes = {"POSITION": self.accessor(points, "VEC3", bounds=True, target=34962),
                      "NORMAL": self.accessor(normals(points, faces), "VEC3", target=34962)}
        fields = {}
        if weights is not None:
            attributes["WEIGHTS_0"] = self.accessor(weights, "VEC4", target=34962)
            attributes["JOINTS_0"] = self.accessor(joints, "VEC4", 5121, target=34962)
            fields["skin"] = 0
        primitive = {"attributes": attributes,
                     "indices": self.accessor(faces, "SCALAR", 5123 if faces.max() < 65536 else 5125, target=34963),
                     "material": material}
        node = self.node(name, mesh=len(self.doc["meshes"]), extras={"layer": layer, **identity}, **fields)
        self.doc["meshes"].append({"name": name, "primitives": [primitive]})
        return node, primitive

    def channel(self, node, path, values, kind):
        animation = self.doc["animations"][0]
        animation["channels"].append({"sampler": len(animation["samplers"]),
                                      "target": {"node": node, "path": path}})
        animation["samplers"].append({"input": self.clock, "output": self.accessor(values, kind),
                                       "interpolation": "LINEAR"})

    def transforms(self, node, matrices):
        import mujoco as mj

        rotation = np.empty((len(matrices), 4))
        scales = np.linalg.norm(matrices[:, :3, :3], axis=1)
        linear = matrices[:, :3, :3] / scales[:, None, :]
        if (not np.allclose(np.swapaxes(linear, 1, 2) @ linear, np.eye(3), atol=2e-6, rtol=0)
                or not np.allclose(np.linalg.det(linear), 1, atol=2e-6, rtol=0)):
            raise ValueError("invalid TRS rotation, handedness or shear")
        for i, matrix in enumerate(linear):
            mj.mju_mat2Quat(rotation[i], np.ascontiguousarray(matrix.ravel()))
            if i and rotation[i] @ rotation[i - 1] < 0:
                rotation[i] *= -1
        translation = matrices[:, :3, 3]
        for path, values, kind in (("translation", translation, "VEC3"),
                                   ("rotation", rotation[:, [1, 2, 3, 0]], "VEC4")):
            self.channel(node, path, values, kind)
        if not np.allclose(scales, 1, atol=2e-6, rtol=0):
            self.channel(node, "scale", scales, "VEC3")

    def finish(self, path):
        self.blob.extend(bytes(-len(self.blob) % 4))
        self.doc["buffers"] = [{"byteLength": len(self.blob)}]
        doc = json.dumps(self.doc, ensure_ascii=True, separators=(",", ":")).encode()
        doc += b" " * (-len(doc) % 4)
        with path.open("xb") as stream:
            stream.write(struct.pack("<4sII", b"glTF", 2, 28 + len(doc) + len(self.blob)))
            stream.write(struct.pack("<I4s", len(doc), b"JSON") + doc)
            stream.write(struct.pack("<I4s", len(self.blob), b"BIN\0") + self.blob)
