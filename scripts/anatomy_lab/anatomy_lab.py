"""An isolated Anatomy Lab registry and scene contract."""

from collections import deque
from contextlib import closing
from functools import cached_property
import hashlib
import json
from math import atan, degrees
from pathlib import Path
import re
import sqlite3
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.types import FiniteFloat

from human_models_mcp.results import error


Fma = Annotated[str, Field(pattern=r"^FMA[1-9][0-9]{0,8}$")]
Fj = Annotated[str, Field(pattern=r"^FJ[0-9]{1,8}M?$")]
Vec3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
Side = Literal["left", "right", "midline", "unpaired", "unknown"]
Predicate = Literal["is_a", "part_of", "has_part"]
Layer = Literal["bones", "muscles", "organs", "vasculature", "other"]
DisplayLayer = Literal["artery", "bone", "cartilage", "digestive", "endocrine", "fascia",
                       "ligament", "lymphatic", "muscle", "nervous", "organ", "other",
                       "reproductive", "respiratory", "skin", "tissue", "urinary", "vein"]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PackName = Annotated[str, Field(pattern=r"^pack-[0-9]{2,4}(?:-[0-9]{2,4})?\.glb$")]
MembershipVersion = Literal["4.3", "4.3i", "4.3+4.3i"]
MEMBERSHIP_SOURCES = {"4.3": "bp3d_43_components", "4.3i": "bp3d_43i_components"}
FRAME = "bp3d_4_3_native_mm"
CLINICAL_NEEDS = [
    "A clinical source for the specific examination and population",
    "Surface landmarks and sound transmission evidence linked to that examination",
]
CLINICAL_TERMS = re.compile(
    r"auscult|stethoscope|heart sounds"
    r"|\u0430\u0443\u0441\u043a\u0443\u043b\u044c\u0442"
    r"|\u0441\u0442\u0435\u0442\u043e\u0441\u043a\u043e\u043f"
    r"|\u0442\u043e\u043d\u044b \u0441\u0435\u0440\u0434\u0446\u0430",
    re.I,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceRequest(Contract):
    operation: Literal["atlas.list_sources", "atlas.get_manifest", "anatomy.coverage"]


class ConceptRequest(Contract):
    operation: Literal["anatomy.describe", "anatomy.components", "anatomy.relationships"]
    concept: Fma
    predicate: Predicate | None = None
    source_id: str | None = Field(default=None, max_length=80)
    depth: int = Field(default=1, ge=1, le=3)
    direction: Literal["out", "in"] = "out"
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=100)
    include_labels: bool = False


class Representation(Contract):
    dataset: Literal["BodyParts3D"]
    mesh_version: Literal["4.3"]
    membership_version: MembershipVersion


class Search(Contract):
    operation: Literal["anatomy.search"]
    query: str = Field(min_length=1, max_length=160)
    side: Side | None = None
    limit: int = Field(default=20, ge=1, le=50)
    representation: Representation | None = None


class Resolve(Contract):
    operation: Literal["anatomy.resolve"]
    concept: Fma
    representation: Representation
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=50, ge=1, le=200)


class Identify(Contract):
    operation: Literal["anatomy.identify"]
    mesh: Fj
    representation: Representation
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=50)


class CompositeBinding(Contract):
    representation: Representation
    asset_manifest_sha256: Sha
    selection_sha256: Sha


class CompositeView(Contract):
    context_fj_ids: list[Fj] = Field(default_factory=list, max_length=64)
    isolated: bool = False
    inspected_fj: Fj | None = None
    hidden_layers: list[DisplayLayer] | None = Field(default=None, max_length=18)
    context_opacity: float | None = Field(default=None, ge=0.05, le=1)


class Spatial(Contract):
    operation: Literal["anatomy.spatial_query"]
    method: Literal["nearest", "raycast", "relative", "clinical"]
    frame: str = Field(default=FRAME, min_length=1, max_length=64)
    mesh: Fj | None = None
    other_mesh: Fj | None = None
    point: Vec3 | None = None
    direction: Vec3 | None = None


class Camera(Contract):
    frame: Literal["bp3d_4_3_native_mm", "packed_atlas_m", "mujoco_world_m"] = FRAME
    view_asset_sha256: Sha | None = None
    fov_axis: Literal["vertical", "horizontal"] = "vertical"
    position: Vec3 = (0, -1500, 850)
    target: Vec3 = (0, 0, 850)
    up: Vec3 = (0, 0, 1)
    fov_degrees: float = Field(default=40, gt=1, lt=150)


class MotionBinding(Contract):
    run_id: UUID
    state_index: int = Field(ge=0, le=100000)
    frame_time: FiniteFloat
    state_sha256: Sha
    motion_sha256: Sha


class Scene(Contract):
    schema_version: Literal["hmm.anatomy.scene/1"] = "hmm.anatomy.scene/1"
    atlas_sha256: Sha
    selection: list[Fma] = Field(default_factory=list, max_length=100)
    visible_layers: list[Layer] = Field(default_factory=list, max_length=5)
    camera: Camera = Field(default_factory=Camera)
    motion: MotionBinding | None = None
    evidence: Literal["source_geometry", "registered_illustrative"] = "source_geometry"
    composite: CompositeBinding | None = None
    composite_view: CompositeView | None = None


class SceneRequest(Contract):
    operation: Literal["scene.create", "scene.select", "scene.set_layers", "scene.export"]
    scene: Scene | None = None
    selection: list[Fma] = Field(default_factory=list, max_length=100)
    visible_layers: list[Layer] = Field(default_factory=list, max_length=5)
    camera: Camera = Field(default_factory=Camera)
    representation: Representation | None = None


class MotionRequest(Contract):
    operation: Literal["motion.open_saved_run", "motion.set_frame"]
    run_id: UUID
    scene: Scene | None = None
    state_index: int | None = Field(default=None, ge=0, le=100000)


class WholeCamera(Contract):
    position: Vec3
    target: Vec3
    fov: FiniteFloat = Field(ge=5, le=100)


class WholeView(Contract):
    schema_version: Literal["hmm.anatomy.motion-view/1"] = "hmm.anatomy.motion-view/1"
    run_id: UUID
    motion_sha256: Sha
    state_index: int = Field(ge=0, le=400)
    layers: list[Literal["BODY", "SKELETON", "MUSCLES", "ORGANS", "SKIN", "OVERLAYS"]] = Field(max_length=6)
    camera: WholeCamera


class WholeDiscover(Contract):
    operation: Literal["whole.discover"]


class WholeOpen(Contract):
    operation: Literal["whole.open"]
    run_id: UUID


class WholeSetView(Contract):
    operation: Literal["whole.set_view"]
    run_id: UUID
    view: WholeView

    @property
    def same_run(self):
        return self.view.run_id == self.run_id


class WholeArtifact(Contract):
    operation: Literal["whole.artifact"]
    run_id: UUID
    artifact_id: Literal["motion.glb", "coverage.json", "scene.blend", "assisted-pushup.mp4"]


class WholeContact(Contract):
    operation: Literal["whole.contact"]
    run_id: UUID
    part: str = Field(min_length=1, max_length=100)
    sample: int = Field(strict=True, ge=0, le=400)


WHOLE_REQUESTS = (WholeDiscover, WholeOpen, WholeSetView, WholeArtifact, WholeContact)


Request = Annotated[SourceRequest | Search | ConceptRequest | Resolve | Identify | Spatial | SceneRequest | MotionRequest
                    | WholeDiscover | WholeOpen | WholeSetView | WholeArtifact | WholeContact,
                    Field(discriminator="operation")]
REQUEST = TypeAdapter(Request)
FMA_ID = TypeAdapter(Fma)
FJ_ID = TypeAdapter(Fj)
HASH = TypeAdapter(Sha)
PACK_NAME = TypeAdapter(PackName)
SIDE = TypeAdapter(Side)
RELATION = TypeAdapter(Predicate)
BUDGET_EDGES = 20000
MAX_CATALOG_BYTES = 64 * 1024 * 1024
MAX_MESH_BYTES = 16 * 1024 * 1024
MAX_PACK_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 10000
BP_ID = re.compile(r"BP[0-9]{1,12}")

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE provenance(id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE anatomy_concept(id TEXT PRIMARY KEY, label TEXT NOT NULL, side TEXT NOT NULL, source_id
  TEXT NOT NULL REFERENCES provenance(id));
CREATE VIRTUAL TABLE anatomy_fts USING fts5(id UNINDEXED,label,tokenize='unicode61');
CREATE TABLE geometry_part(id TEXT PRIMARY KEY, bp_id TEXT, fma_id TEXT REFERENCES anatomy_concept(id),
  filename TEXT NOT NULL, bytes INTEGER, sha256 TEXT, source_id TEXT NOT NULL REFERENCES provenance(id),
  master_fma_id TEXT REFERENCES anatomy_concept(id), pinned_filename_fma_id TEXT, identity_source_id TEXT,
  obj_concept_id TEXT, obj_representation_id TEXT, identity_status TEXT NOT NULL);
CREATE INDEX geometry_bp_id ON geometry_part(bp_id);
CREATE INDEX geometry_obj_bp_id ON geometry_part(obj_representation_id);
CREATE TABLE concept_geometry(concept TEXT NOT NULL REFERENCES anatomy_concept(id),
  mesh TEXT NOT NULL, mapping TEXT NOT NULL, source_id TEXT NOT NULL
  REFERENCES provenance(id), PRIMARY KEY(concept,mesh,source_id,mapping)) WITHOUT ROWID;
CREATE INDEX concept_geometry_mesh ON concept_geometry(mesh,source_id,concept);
CREATE TABLE anatomy_relation(subject TEXT NOT NULL REFERENCES anatomy_concept(id), predicate TEXT NOT NULL,
  object TEXT NOT NULL REFERENCES anatomy_concept(id), source_id TEXT NOT NULL REFERENCES provenance(id),
  inferred INTEGER NOT NULL, source_predicate TEXT NOT NULL,
  PRIMARY KEY(subject,predicate,object,source_id,inferred,source_predicate)) WITHOUT ROWID;
CREATE INDEX relation_object ON anatomy_relation(object,predicate,subject);
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_bounded(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"invalid local asset: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"asset exceeds byte budget: {path.name}")
    return data


def installed(path, size):
    return size is not None and not path.is_symlink() and path.is_file() and path.stat().st_size == size


class PackRecord(Contract):
    presets: list[str] = Field(max_length=32)
    parts: list[Fj] = Field(min_length=1, max_length=MAX_MEMBERS)
    sha256: Sha
    bytes: int = Field(strict=True, ge=28, le=MAX_PACK_BYTES)


class PackManifest(Contract):
    format: Literal["hmm-glb-packs/2"]
    source_sha256: Sha
    original_glb_sha256: Sha
    packs: dict[PackName, PackRecord] = Field(min_length=1, max_length=MAX_MEMBERS)


def fma(value):
    return FMA_ID.validate_python(f"FMA{value}" if type(value) is int else value)


def clinical():
    return {
        **error("unsupported", "Clinical auscultation requires independent clinical evidence"),
        "reason": "NOT_SUPPORTED_BY_ANATOMICAL_GEOMETRY",
        "needed_evidence": CLINICAL_NEEDS,
    }


class Registry:
    """Local, normalized source catalog with one query-only connection per process."""

    def __init__(self, catalog, mesh_dir, motion_path=None, site=None):
        self.whole = None
        raw = read_bounded(Path(catalog), MAX_CATALOG_BYTES)
        self.atlas_sha256 = digest(raw)
        self.catalog = json.loads(raw)
        if self.catalog.get("schema_version") != 1:
            raise ValueError("unsupported atlas catalog schema")
        self.mesh_dir = Path(mesh_dir)
        if self.mesh_dir.is_symlink():
            raise ValueError("mesh directory cannot be a symlink")
        inventory = Path(catalog).with_name("verified_mesh_inventory.json")
        self.inventory = json.loads(read_bounded(inventory, MAX_CATALOG_BYTES)) if inventory.is_file() else {}
        self.motion_path = Path(motion_path) if motion_path else None
        self.pack_dir = (Path(site) if site else Path(catalog).parent / "site") / "full/site/packs"
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.query_lock = Lock()
        self.db.row_factory = sqlite3.Row
        try:
            with self.db:
                self.db.executescript(SCHEMA)
                self._import()
            self.db.execute("PRAGMA query_only=ON")
        except BaseException:
            self.db.close()
            raise

    def _import(self):
        for source in self.catalog["sources"]:
            self.db.execute("INSERT INTO provenance VALUES (?,?)",
                            (source["id"], canonical(source).decode()))
        for concept in self.catalog["concepts"]:
            identifier = fma(concept["fma_id"])
            label = concept["label"]
            if not isinstance(label, str) or not 1 <= len(label) <= 1000:
                raise ValueError("invalid concept label")
            side = SIDE.validate_python(concept.get("side", "unknown"))
            self.db.execute("INSERT INTO anatomy_concept VALUES (?,?,?,?)",
                            (identifier, label, side, concept["source_id"]))
            self.db.execute("INSERT INTO anatomy_fts VALUES (?,?)", (identifier, label))
        for mesh in self.catalog["meshes"]:
            identifier = FJ_ID.validate_python(mesh["fj_id"])
            filename = mesh.get("filename", identifier + ".obj")
            sha = mesh.get("sha256")
            size = mesh.get("bytes")
            if filename != identifier + ".obj" or (
                sha is not None and (not HASH.validate_python(sha) or type(size) is not int or size < 1)
            ):
                raise ValueError("invalid mesh asset record")
            concept = fma(mesh["fma_id"]) if mesh.get("fma_id") else None
            raw = self.inventory.get(identifier, {})
            if raw and (raw["sha256"] != sha or raw["bytes"] != size):
                raise ValueError("mesh inventory and source record disagree")
            filename_fma = fma(mesh["pinned_filename_fma_id"]) if mesh.get("pinned_filename_fma_id") else None
            obj_fma = raw.get("obj_concept_id") if raw else mesh.get("obj_concept_id")
            obj_fma = fma(obj_fma) if obj_fma else None
            obj_bp = raw.get("obj_representation_id") if raw else mesh.get("obj_representation_id")
            bp = mesh.get("bp_id")
            if any(value is not None and (not isinstance(value, str) or not BP_ID.fullmatch(value))
                   for value in (obj_bp, bp)):
                raise ValueError("invalid BP representation identifier")
            disputed = (mesh.get("identity_status") == "DISPUTED"
                        or len({identifier for identifier in (concept, filename_fma, obj_fma) if identifier}) > 1)
            self.db.execute("INSERT INTO geometry_part VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (identifier, bp, None if disputed else concept, filename, size, sha,
                             mesh["source_id"], concept, filename_fma, mesh.get("identity_source_id"),
                             obj_fma, obj_bp,
                             "DISPUTED" if disputed else "source_record"))
        for link in self.catalog["components"]:
            self.db.execute("INSERT INTO concept_geometry VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                            (fma(link["fma_id"]), FJ_ID.validate_python(link["fj_id"]),
                             link["mapping"], link["source_id"]))
        for edge in self.catalog["relations"]:
            inferred = edge["inferred"]
            if inferred is not None and type(inferred) is not bool:
                raise ValueError("anatomical edge needs an explicit or unknown inference flag")
            predicate = RELATION.validate_python(edge["predicate"])
            self.db.execute("INSERT INTO anatomy_relation VALUES (?,?,?,?,?,?)",
                            (fma(edge["subject_fma"]), predicate, fma(edge["object_fma"]),
                             edge["source_id"], -1 if inferred is None else inferred,
                             edge.get("source_predicate", predicate)))

    def rows(self, sql, parameters=()):
        with self.query_lock, closing(self.db.execute(sql, parameters)) as cursor:
            return [dict(row) for row in cursor]

    def provenance(self, identifier):
        return json.loads(self.rows("SELECT data FROM provenance WHERE id=?", (identifier,))[0]["data"])

    def sources(self):
        return [json.loads(row["data"]) for row in self.rows("SELECT data FROM provenance ORDER BY id")]

    def coverage(self):
        return {
            "status": "ok",
            "catalog_sha256": self.atlas_sha256,
            "atlas_metadata": self.catalog.get("manifest", {}),
            "concepts_indexed": self.rows("SELECT count(*) n FROM anatomy_concept")[0]["n"],
            "mesh_records": self.rows("SELECT count(*) n FROM geometry_part")[0]["n"],
            "mesh_records_with_hash": self.rows("SELECT count(sha256) n FROM geometry_part")[0]["n"],
            "mesh_integrity": "verified on read",
            "disputed_primary_fma": self.rows("SELECT count(*) n FROM geometry_part WHERE identity_status='DISPUTED'")[0]["n"],
            "obj_vs_master_bp_disagreements": self.rows(
                "SELECT count(*) n FROM geometry_part WHERE obj_representation_id != bp_id")[0]["n"]
                if self.rows("SELECT 1 FROM geometry_part WHERE obj_representation_id IS NOT NULL LIMIT 1") else None,
            "component_counts": self.rows(
                "SELECT source_id,mapping,count(*) n FROM concept_geometry GROUP BY source_id,mapping"),
            "relation_counts": [{**row, "inferred": None if row["inferred"] == -1 else bool(row["inferred"])}
                                for row in self.rows("SELECT source_id,predicate,inferred,count(*) n FROM "
                                                     "anatomy_relation GROUP BY source_id,predicate,inferred")],
            "4.3i_anatomical_edges": "PARTIAL",
            "authored_43i_inferred_edges": "NOT_VERIFIED",
        }

    def describe(self, identifier):
        results = self.rows("SELECT * FROM anatomy_concept WHERE id=?", (identifier,))
        if not results:
            return error("unknown", "FMA identifier is absent from the installed catalog")
        concept = results[0]
        return {"status": "ok", "concept": concept, "provenance": self.provenance(concept["source_id"]),
                "label_role": "source data", "side_frame": "patient"}

    def search(self, query, side, limit):
        if CLINICAL_TERMS.search(query):
            return clinical()
        clean = query.strip()
        identifier = clean.upper().replace("FMA:", "FMA")
        if re.fullmatch(r"FMA[0-9]+", identifier):
            result = self.describe(identifier)
            if side and result.get("concept", {}).get("side") != side:
                return error("unknown", "FMA identifier does not match the requested patient side")
            return result
        if re.fullmatch(r"(?:FJ[0-9]+M?|BP[0-9]+)", identifier):
            rows = self.rows(
                """SELECT p.*,c.side FROM geometry_part p LEFT JOIN anatomy_concept c ON c.id=p.fma_id
                   WHERE (p.id=? OR p.bp_id=? OR p.obj_representation_id=?)
                     AND (? IS NULL OR c.side=?) ORDER BY p.id LIMIT ?""",
                (identifier, identifier, identifier, side, side, limit))
            return {"status": "ok", "namespace": identifier[:2], "matches": rows, "side_frame": "patient"}
        tokens = re.findall(r"[^\W_]+", clean, flags=re.UNICODE)
        if not 1 <= len(tokens) <= 20:
            return error("invalid_input", "search requires 1–20 label tokens or one source identifier")
        expression = " AND ".join('"' + token + '"*' for token in tokens)
        matches = self.rows(
            """SELECT c.* FROM anatomy_fts ft JOIN anatomy_concept c ON ft.id=c.id
               WHERE anatomy_fts MATCH ? AND (? IS NULL OR c.side=?)
               ORDER BY lower(c.label)!=lower(?),rank,c.id LIMIT ?""",
            (expression, side, side, clean, limit),
        )
        return {"status": "ok", "namespace": "FMA", "matches": matches, "side_frame": "patient",
                "resolution": "ambiguous" if len(matches) > 1 else "unique" if matches else "unknown"}

    def components(self, query):
        rows = self.rows(
            """SELECT g.mesh AS fj_id,p.bp_id,p.fma_id AS primary_fma,p.bytes,p.sha256,
                      g.mapping,g.source_id,p.source_id AS mesh_source_id,
                      p.identity_status,p.obj_representation_id,p.master_fma_id,p.pinned_filename_fma_id
               FROM concept_geometry g LEFT JOIN geometry_part p ON p.id=g.mesh WHERE concept=?
               ORDER BY g.source_id,g.mesh,g.mapping LIMIT ? OFFSET ?""",
            (query.concept, query.limit + 1, query.offset),
        )
        total = self.rows("SELECT count(DISTINCT mesh) n FROM concept_geometry WHERE concept=?",
                          (query.concept,))[0]["n"]
        for row in rows:
            row["representation"] = ("disputed_identity" if row["identity_status"] == "DISPUTED" else
                                     "compound_member" if total > 1 else
                                     "source_mesh" if row["primary_fma"] == query.concept else "mapped_component")
        sources = {row["source_id"] for row in rows} | {row["mesh_source_id"] for row in rows if row["mesh_source_id"]}
        return self.page(query, rows, "components", mesh_count=total, relation_scope="concept_to_geometry_membership",
                         provenance={identifier: self.provenance(identifier) for identifier in sorted(sources)})

    def membership_sources(self, representation):
        atlas = self.catalog.get("manifest", {})
        if (atlas.get("atlas_id"), atlas.get("version")) != (representation.dataset, representation.mesh_version):
            raise LookupError("The requested dataset and mesh version are not installed")
        expected = [MEMBERSHIP_SOURCES[v] for v in representation.membership_version.split("+")]
        sources = {s["id"]: s for s in self.sources()}
        if any(s not in sources or sources[s].get("version") != v
               for v, s in zip(representation.membership_version.split("+"), expected, strict=True)):
            raise LookupError("The requested membership version is not installed")
        return {s: sources[s] for s in expected}

    def composite_search(self, request, result):
        sources = self.membership_sources(request.representation)
        scope = tuple(sources)
        for concept in [result["concept"]] if "concept" in result else result.get("matches", []):
            counts = self.rows(
                "SELECT count(DISTINCT mesh) AS n FROM concept_geometry WHERE concept=? "
                "AND source_id IN (?,?)", (concept["id"], scope[0], scope[-1]))
            concept["visual_membership_count"] = counts[0]["n"]
        return result

    @cached_property
    def display(self):
        if any(path.is_symlink() for path in (self.pack_dir, *list(self.pack_dir.parents)[:2])):
            raise ValueError("invalid display pack location")
        path = self.pack_dir / "manifest.json"
        if not path.is_file():
            raise LookupError("No composite display pack index is installed; provision the viewer")
        data = read_bounded(path, MAX_CATALOG_BYTES)
        index = PackManifest.model_validate_json(data)
        source = {r["id"]: r["sha256"] for r in self.rows("SELECT id,sha256 FROM geometry_part")}
        if index.source_sha256 != digest(canonical(source)):
            raise ValueError("Display pack index belongs to a different source mesh inventory")
        pack_of = {}
        packs = {}
        for name, record in sorted(index.packs.items()):
            for fj in record.parts:
                if fj not in source or fj in pack_of or not source[fj]:
                    raise ValueError("Display pack index has an invalid or duplicate FJ identity")
                pack_of[fj] = name
            packs[name] = {"bytes": record.bytes, "sha256": record.sha256}
        return index.source_sha256, digest(data), pack_of, packs

    def pack_bytes(self, name, expected):
        PACK_NAME.validate_python(name)
        _, _, _, packs = self.display
        if name not in packs:
            raise LookupError("Unknown display pack")
        record = packs[name]
        if expected != record["sha256"]:
            raise ValueError("Display pack digest does not match the installed index")
        data = read_bounded(self.pack_dir / name, MAX_PACK_BYTES)
        if len(data) != record["bytes"] or digest(data) != expected:
            raise ValueError("Display pack bytes do not match the installed index")
        return data

    def composite(self, identifier, representation):
        sources = self.membership_sources(representation)
        scope = list(sources)
        rows = self.rows(
            """SELECT g.mesh AS fj_id,g.source_id AS membership_source,g.mapping,p.*
               FROM concept_geometry g LEFT JOIN geometry_part p ON p.id=g.mesh
               WHERE concept=? AND g.source_id IN (?,?) ORDER BY g.mesh,g.source_id,g.mapping
               LIMIT ?""", (identifier, scope[0], scope[-1], 4 * MAX_MEMBERS + 1))
        if len(rows) > 4 * MAX_MEMBERS:
            raise ValueError("Visual membership exceeds the source-row budget")
        members = {}
        for row in rows:
            fj = row["fj_id"]
            if fj not in members:
                fmas = {row[k] for k in ("master_fma_id", "pinned_filename_fma_id", "obj_concept_id") if row[k]}
                bp_conflict = bool(row["bp_id"] and row["obj_representation_id"]
                                   and row["bp_id"] != row["obj_representation_id"])
                members[fj] = {
                    "fj_id": fj, "memberships": [], "mesh_sha256": row["sha256"], "mesh_source": row["source_id"],
                    "claims": {"master_fma": row["master_fma_id"], "mirror_filename_fma": row["pinned_filename_fma_id"],
                               "obj_fma": row["obj_concept_id"], "master_bp": row["bp_id"],
                               "obj_bp": row["obj_representation_id"], "master_source": row["identity_source_id"]},
                    "fma_conflict": row["identity_status"] == "DISPUTED" or len(fmas) > 1,
                    "bp_conflict": bp_conflict,
                    "unresolved_identity": not (fmas and row["obj_concept_id"] and row["obj_representation_id"]),
                    "source_available": bool(row["sha256"]) and
                        installed(self.mesh_dir / row["filename"], row["bytes"]),
                }
            members[fj]["memberships"].append({"source_id": row["membership_source"], "mapping": row["mapping"]})
        if len(members) > MAX_MEMBERS:
            raise ValueError("Visual membership exceeds the supported FJ count")
        source_sha, manifest_sha, pack_of, packs = self.display
        required = {}
        source_counts = dict.fromkeys(scope, 0)
        for fj, member in members.items():
            for source_id in {claim["source_id"] for claim in member["memberships"]}:
                source_counts[source_id] += 1
            pack = pack_of.get(fj)
            if pack is not None and pack not in required:
                required[pack] = installed(self.pack_dir / pack, packs[pack]["bytes"])
            member["pack"] = pack
            member["renderable"] = member["source_available"] and required.get(pack, False)
        counts = {"members": len(members),
                  "renderable": sum(m["renderable"] for m in members.values()),
                  "missing_source": sum(not m["source_available"] for m in members.values()),
                  "missing_display": sum(not required.get(m["pack"], False) for m in members.values()),
                  **{key: sum(m[key] for m in members.values())
                     for key in ("fma_conflict", "bp_conflict", "unresolved_identity")}}
        warnings = [key for key, count in counts.items() if count and key not in {"members", "renderable"}]
        if len(scope) > 1 and any(n != len(members) for n in source_counts.values()):
            warnings.append("version_memberships_differ")
        coverage = ("UNAVAILABLE" if not counts["renderable"] else "PARTIAL"
                    if any(counts[key] for key in counts.keys() - {"members", "renderable"}) else "AVAILABLE")
        ordered = list(members.values())
        plan = {m["pack"]: packs[m["pack"]] for m in ordered if m["renderable"]}
        selection_hash = digest(canonical({
            "concept": identifier, "atlas": self.atlas_sha256, "manifest": manifest_sha,
            "representation": representation.model_dump(), "members": ordered,
        }))
        return ordered, plan, {
            "schema_version": "hmm.anatomy.composite/1",
            "atlas_sha256": self.atlas_sha256, "asset_manifest_sha256": manifest_sha,
            "source_mesh_inventory_sha256": source_sha, "selection_sha256": selection_hash,
            "representation": representation.model_dump(),
            "coverage": coverage, "counts": counts, "warnings": warnings,
            "source_membership_counts": source_counts, "pack_count": len(plan),
            "pack_bytes": sum(p["bytes"] for p in plan.values()),
            "provenance": {identifier: self.provenance(identifier) for identifier in sorted(
                set(scope) | {s for m in ordered for s in (m["mesh_source"], m["claims"]["master_source"]) if s})},
            "relation_scope": "visual_membership",
        }

    def resolve(self, query):
        concept = self.describe(query.concept)
        if concept["status"] != "ok":
            return concept
        members, plan, details = self.composite(query.concept, query.representation)
        page = members[query.offset:query.offset + query.limit]
        return {**concept, **details, "members": page,
                "packs": {name: plan[name] for name in sorted({m["pack"] for m in page if m["renderable"]})},
                "next_offset": query.offset + len(page) if query.offset + len(page) < len(members) else None}

    def identify(self, query):
        scope = tuple(self.membership_sources(query.representation))
        rows = self.rows("SELECT * FROM geometry_part WHERE id=?", (query.mesh,))
        if not rows:
            return error("unknown", "FJ identifier is absent from the installed catalog")
        mesh = rows[0]
        claims = {key: mesh[key] for key in ("master_fma_id", "pinned_filename_fma_id", "obj_concept_id")}
        candidates = {}
        for kind, identifier in claims.items():
            if identifier:
                candidates.setdefault(identifier, {"identity_claims": [], "memberships": []})["identity_claims"].append(kind)
        links = self.rows(
            "SELECT concept,source_id,mapping FROM concept_geometry WHERE mesh=? AND source_id IN (?,?) "
            "ORDER BY concept,source_id,mapping LIMIT ?",
            (query.mesh, scope[0], scope[-1], BUDGET_EDGES + 1))
        if len(links) > BUDGET_EDGES:
            raise ValueError("FJ membership exceeds the source-row budget")
        for link in links:
            identifier = link.pop("concept")
            candidates.setdefault(identifier, {"identity_claims": [], "memberships": []})["memberships"].append(link)
        ordered = sorted(candidates, key=lambda identifier: (not candidates[identifier]["identity_claims"], identifier))
        page = []
        for identifier in ordered[query.offset:query.offset + query.limit]:
            concept = self.describe(identifier).get("concept") or {"id": identifier, "label": None, "side": "unknown"}
            page.append({**concept, **candidates[identifier]})
        return {
            "status": "ok", "mesh": mesh, "representation": query.representation.model_dump(),
            "bp_conflict": bool(mesh["bp_id"] and mesh["obj_representation_id"] and
                                mesh["bp_id"] != mesh["obj_representation_id"]),
            "candidates": page, "candidate_count": len(ordered),
            "next_offset": query.offset + len(page) if query.offset + len(page) < len(ordered) else None,
            "side_frame": "patient", "relation_scope": "identity_claims_and_visual_memberships",
            "provenance": {identifier: self.provenance(identifier) for identifier in sorted(
                set(scope) | {key for key in (mesh["source_id"], mesh["identity_source_id"]) if key})},
        }

    def relationships(self, query):
        source, destination = ("subject", "object") if query.direction == "out" else ("object", "subject")
        sql = (f"SELECT * FROM anatomy_relation WHERE {source}=? "
               "AND (? IS NULL OR predicate=?) AND (? IS NULL OR source_id=?) "
               "ORDER BY subject,predicate,object,source_id,inferred,source_predicate LIMIT ?")
        todo = deque([(query.concept, 0)])
        visited = {query.concept}
        emitted = set()
        report = []
        while todo and len(report) <= query.limit + query.offset:
            current, distance = todo.popleft()
            rows = self.rows(sql, (current, query.predicate, query.predicate,
                                  query.source_id, query.source_id, BUDGET_EDGES + 1))
            for row in rows:
                key = tuple(row.values())
                if key in emitted:
                    continue
                if len(emitted) == BUDGET_EDGES:
                    return self.page(query, report[query.offset:], "relationships", coverage="PARTIAL",
                                     stop_reason="traversal_budget")
                emitted.add(key)
                target = row[destination]
                row["inferred"] = None if row["inferred"] == -1 else bool(row["inferred"])
                row["distance"] = distance + 1
                row["provenance"] = self.provenance(row["source_id"])
                if query.include_labels:
                    row["related_concept"] = self.describe(target)["concept"]
                report.append(row)
                if distance + 1 < query.depth and target not in visited:
                    visited.add(target)
                    todo.append((target, distance + 1))
                if len(report) > query.limit + query.offset:
                    break
        return self.page(query, report[query.offset:], "relationships", coverage="PARTIAL",
                         traversal="stored edges only")

    @staticmethod
    def page(query, rows, field, **metadata):
        return {"status": "ok", "concept": query.concept, field: rows[:query.limit],
                "next_offset": query.offset + query.limit if len(rows) > query.limit else None, **metadata}

    def mesh(self, identifier):
        rows = self.rows("SELECT * FROM geometry_part WHERE id=?", (identifier,))
        if not rows or not rows[0]["sha256"]:
            raise LookupError("no verified mesh record for " + identifier)
        asset = rows[0]
        data = read_bounded(self.mesh_dir / asset["filename"], MAX_MESH_BYTES)
        if len(data) != asset["bytes"] or digest(data) != asset["sha256"]:
            raise ValueError("mesh size or SHA-256 mismatch for " + identifier)
        return asset, data

    def scene(self, request):
        if request.operation == "scene.create":
            scene = Scene(atlas_sha256=self.atlas_sha256, selection=request.selection,
                          visible_layers=request.visible_layers, camera=request.camera)
        elif request.scene is None:
            return error("invalid_input", "scene document required")
        else:
            scene = request.scene
            if request.operation == "scene.select":
                if scene.composite:
                    previous = self.scene_result(scene)
                    if previous["status"] != "ok":
                        return previous
                scene = scene.model_copy(update={"selection": request.selection, "composite": None,
                                                 "composite_view": None})
            elif request.operation == "scene.set_layers":
                scene = scene.model_copy(update={"visible_layers": request.visible_layers})
        if request.representation:
            if request.operation not in {"scene.create", "scene.select"} or scene.motion or len(set(scene.selection)) != 1:
                return error("invalid_input", "a composite binding requires one static FMA selection")
            if self.describe(scene.selection[0])["status"] != "ok":
                return error("unknown", "scene contains a concept absent from this catalog")
            _, _, details = self.composite(scene.selection[0], request.representation)
            if not details["counts"]["renderable"]:
                return error("unsupported", "the concept has no renderable membership in this version")
            binding = CompositeBinding(representation=request.representation,
                                       asset_manifest_sha256=details["asset_manifest_sha256"],
                                       selection_sha256=details["selection_sha256"])
            scene = scene.model_copy(update={"composite": binding, "composite_view": CompositeView()})
        return self.scene_result(scene)

    def scene_result(self, scene):
        if scene.atlas_sha256 != self.atlas_sha256:
            return error("unsupported", "scene belongs to a different atlas catalog")
        identifiers = sorted(set(scene.selection))
        for identifier in identifiers:
            if not self.rows("SELECT 1 FROM anatomy_concept WHERE id=?", (identifier,)):
                return error("unknown", "scene contains a concept absent from this catalog")
        forward = [t - p for t, p in zip(scene.camera.target, scene.camera.position, strict=True)]
        x, y, z = forward
        u, v, w = scene.camera.up
        if (max(map(abs, (*scene.camera.position, *scene.camera.target, *scene.camera.up))) > 1e6
                or max(map(abs, (y*w-z*v, z*u-x*w, x*v-y*u))) < 1e-9):
            return error("invalid_input", "camera view and up vectors must be bounded and independent")
        if scene.camera.frame == "packed_atlas_m" and not scene.camera.view_asset_sha256:
            return error("invalid_input", "packed cameras require a view-asset digest")
        if scene.composite:
            if len(identifiers) != 1 or scene.motion:
                return error("invalid_input", "a composite scene requires one static FMA selection")
            members, _, details = self.composite(identifiers[0], scene.composite.representation)
            if (scene.composite.asset_manifest_sha256 != details["asset_manifest_sha256"]
                    or scene.composite.selection_sha256 != details["selection_sha256"]
                    or (scene.camera.frame == "packed_atlas_m" and
                        scene.camera.view_asset_sha256 != details["source_mesh_inventory_sha256"])):
                return error("integrity_error", "composite scene does not match the installed display or FJ selection")
            view = scene.composite_view or CompositeView()
            selected = {member["fj_id"] for member in members if member["renderable"]}
            context = sorted(set(view.context_fj_ids))
            _, _, pack_of, packs = self.display
            if (not selected or (view.inspected_fj is not None and view.inspected_fj not in selected.union(context))
                    or selected.intersection(context)
                    or any(fj not in pack_of or not installed(self.pack_dir / pack_of[fj], packs[pack_of[fj]]["bytes"])
                           for fj in context)):
                return error("integrity_error", "scene context or inspected FJ is unavailable for this selection")
            hidden = sorted(set(view.hidden_layers)) if view.hidden_layers else None
            scene = scene.model_copy(update={"composite_view": view.model_copy(
                update={"context_fj_ids": context, "hidden_layers": hidden})})
        elif scene.composite_view is not None:
            return error("invalid_input", "composite view requires a resolved selection")
        if scene.motion:
            motion, motion_sha = self.motion_data(scene.motion.run_id)
            expected = next((frame for frame in motion["frames"]
                             if frame["state_index"] == scene.motion.state_index), None)
            if (scene.evidence != "registered_illustrative" or not expected or
                    scene.motion.motion_sha256 != motion_sha or
                    scene.motion.state_sha256 != expected["state_sha256"] or
                    scene.motion.frame_time != expected["frame_time"] or
                    scene.camera != self.motion_camera(motion) or
                    not set(identifiers) <= {p["fma_id"] for p in motion["structures"].values()}):
                return error("integrity_error", "scene motion does not match the verified saved frame")
        elif scene.evidence != "source_geometry" or scene.camera.frame == "mujoco_world_m":
            return error("invalid_input", "registered scene requires saved-frame evidence")
        scene = scene.model_copy(update={"selection": identifiers, "visible_layers": sorted(set(scene.visible_layers))})
        payload = scene.model_dump(mode="json", exclude={"composite", "composite_view"} if not scene.composite else set())
        if scene.composite:
            for field in ("hidden_layers", "context_opacity"):
                if payload["composite_view"][field] is None:
                    del payload["composite_view"][field]
        return {"status": "ok", "scene": payload, "scene_sha256": digest(canonical(payload))}

    def motion_data(self, run_id):
        if not self.motion_path:
            raise LookupError("registered motion is unavailable")
        data = read_bounded(self.motion_path, 4 * 1024 * 1024)
        metadata = json.loads(data)
        if metadata["run_id"] != str(run_id):
            raise LookupError("run has no installed registration")
        self.verify_motion(metadata)
        return metadata, digest(data)

    def verify_motion(self, metadata):
        import io

        import numpy as np

        from human_models_mcp.atlas import atlas_lock, atlas_lock_digest

        lock = atlas_lock()
        if metadata["schema_version"] != "1.0" or metadata["atlas_hash"] != atlas_lock_digest(lock):
            raise ValueError("unexpected motion schema or regional atlas hash")
        run = self.motion_path.parent.parent / "results" / str(UUID(metadata["run_id"]))
        if run.is_symlink():
            raise ValueError("invalid motion run location")
        manifest_bytes = read_bounded(run / "manifest.json", 2 * 1024 * 1024)
        if digest(manifest_bytes) != metadata["source_manifest_sha256"]:
            raise ValueError("saved run manifest SHA-256 mismatch")
        manifest = json.loads(manifest_bytes)
        trajectory = read_bounded(run / "trajectory.npz", 2 * 1024 * 1024)
        if (manifest["scenario_id"] not in {"pushup_flat_palm", "pushup_palms"} or manifest["status"] != "computed"
                or manifest["run_id"] != metadata["run_id"]
                or digest(trajectory) != metadata["source_sha"]
                or metadata["source_sha"] != manifest["artifacts"]["trajectory.npz"]["sha256"]):
            raise ValueError("saved trajectory or scenario mismatch")
        for filename, asset in lock["files"].items():
            part = metadata["structures"][asset["object_id"]]
            if (part["source_sha256"] != asset["sha256"] or part["fma_id"] != asset["anatomical_id"]
                    or part["patient_side"] != "right"):
                raise ValueError("registered structure identity mismatch")
            _, data = self.mesh(asset["object_id"])
            if digest(data) != asset["sha256"]:
                raise ValueError("installed regional atlas mesh differs from motion source")
        from human_models_mcp.scene_export import safe_archive

        safe_archive(run / "trajectory.npz")
        with np.load(io.BytesIO(trajectory), allow_pickle=False) as archive:
            states, times = archive["states"], archive["time_s"]
            frames = metadata["frames"]
            if len(frames) != 3 or [f["phase"] for f in frames] != ["start", "bottom", "return"]:
                raise ValueError("motion must contain the three declared phases")
            indices = [f["state_index"] for f in frames]
            if (any(type(i) is not int or i < 0 for i in indices)
                    or not indices[0] < indices[1] < indices[2] < len(states)):
                raise ValueError("invalid motion phase index")
            for frame, index in zip(frames, indices, strict=True):
                if (float(times[index]) != frame["frame_time"] or
                        digest(states[index].tobytes()) != frame["state_sha256"]):
                    raise ValueError("saved frame clock or state SHA-256 mismatch")
                if set(frame["transforms"]) != {"FJ3362", "FJ3368"}:
                    raise ValueError("unsupported motion region")
                for transform in frame["transforms"].values():
                    matrix = np.asarray(transform["matrix"])
                    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
                        raise ValueError("invalid motion matrix")
                    rotation = matrix[:3, :3] * 1000
                    if (not np.array_equal(matrix[3], [0, 0, 0, 1])
                            or not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
                            or not np.isclose(np.linalg.det(rotation), 1, atol=1e-9)):
                        raise ValueError("motion transform must be proper rotation and millimetres to metres")

    def motion(self, request):
        motion, motion_sha = self.motion_data(request.run_id)
        if request.operation == "motion.open_saved_run":
            return {"status": "ok", "run_id": str(request.run_id), "motion_sha256": motion_sha,
                    **{k: motion[k] for k in ("source_sha", "atlas_hash", "scene_sha", "renderer_version",
                                             "device", "camera", "evidence", "coordinates")},
                    "structures": {fj: {k: item[k] for k in ("fma_id", "bp_id", "patient_side", "pose_kind",
                                                            "source_sha256")}
                                   for fj, item in motion["structures"].items()},
                    "frames": [{k: frame[k] for k in ("state_index", "frame_time", "state_sha256")}
                               for frame in motion["frames"]]}
        frame = next((item for item in motion["frames"] if item["state_index"] == request.state_index), None)
        if frame is None:
            return error("unsupported", "state index does not have an installed registration")
        scene = request.scene or Scene(atlas_sha256=self.atlas_sha256)
        binding = MotionBinding(run_id=request.run_id, state_index=frame["state_index"],
                                frame_time=frame["frame_time"], state_sha256=frame["state_sha256"],
                                motion_sha256=motion_sha)
        if not scene.selection:
            scene = scene.model_copy(update={"selection": [p["fma_id"] for p in motion["structures"].values()]})
        scene = scene.model_copy(update={"motion": binding, "evidence": "registered_illustrative",
                                         "camera": self.motion_camera(motion)})
        result = self.scene_result(scene)
        return {**result, "transforms": frame["transforms"]} if result["status"] == "ok" else result

    @staticmethod
    def motion_camera(motion):
        camera = motion["camera"]
        return Camera(frame="mujoco_world_m", position=camera["position_m"], target=camera["target_m"],
                      fov_axis="horizontal", fov_degrees=degrees(2 * atan(18 / camera["lens_mm"])))

    def call(self, request):
        try:
            if isinstance(request, SourceRequest):
                if request.operation == "atlas.list_sources":
                    return {"status": "ok", "sources": self.sources()}
                return {**self.coverage(), "sources": self.sources()} if request.operation == "atlas.get_manifest" else self.coverage()
            if isinstance(request, Search):
                result = self.search(request.query, request.side, request.limit)
                if (request.representation and result["status"] == "ok"
                        and result.get("namespace", "FMA") == "FMA"):
                    return self.composite_search(request, result)
                return result
            if isinstance(request, Resolve):
                return self.resolve(request)
            if isinstance(request, Identify):
                return self.identify(request)
            if isinstance(request, ConceptRequest):
                concept = self.describe(request.concept)
                if concept["status"] != "ok" or request.operation == "anatomy.describe":
                    return concept
                return self.components(request) if request.operation == "anatomy.components" else self.relationships(request)
            if isinstance(request, Spatial):
                from spatial import query

                return query(self, request)
            if isinstance(request, WHOLE_REQUESTS):
                if self.whole is None:
                    return error("not_installed", "whole-body motion is not installed")
                if isinstance(request, WholeSetView) and not request.same_run:
                    return error("invalid_input", "view and request run IDs differ")
                return self.whole.call(request)
            if isinstance(request, SceneRequest):
                return self.scene(request)
            return self.motion(request)
        except (KeyError, OSError, ValueError) as exc:
            return error("integrity_error", str(exc)[:250])
        except LookupError as exc:
            return error("unsupported", str(exc))
