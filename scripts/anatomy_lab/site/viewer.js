import * as THREE from "three";
import { GLTFLoader } from "./npm/node_modules/three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "./npm/node_modules/three/examples/jsm/controls/OrbitControls.js";
import { wholeMotion } from "./whole_motion.js";
import { installExplorer } from "./explorer.js";
import { applyCoreScene, request, resolveComposite } from "./lab_bridge.js";

const el = (id) => document.getElementById(id);
const canvas = el("view");
const context = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
context.setPixelRatio(1);
context.localClippingEnabled = true;
const scene = new THREE.Scene();
scene.background = new THREE.Color().setRGB(.118, .145, .180, THREE.SRGBColorSpace);
const camera = new THREE.PerspectiveCamera(40, 1, .001, 10);
scene.add(camera);
scene.add(new THREE.HemisphereLight(0xd6e7ff, 0xd3c1ab, 1.5));
const keyLight = new THREE.DirectionalLight(0xffffff, 2.3);
keyLight.position.set(.4, .65, 1);
camera.add(keyLight);
const orbit = new OrbitControls(camera, canvas);
const ray = new THREE.Raycaster();
const assetDir = "./full/site/";
async function assetMetadata(path) {
  const response = await fetch(assetDir + path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`Could not load atlas metadata (${response.status})`);
  return response.json();
}
const [metadata, packed] = await Promise.all([assetMetadata("scenes.json"), assetMetadata("packs/manifest.json")]);
const compositeEnabled = packed.format === "hmm-glb-packs/2";
if ((!compositeEnabled && packed.format !== "hmm-glb-packs/1") ||
    packed.source_sha256 !== metadata.source_sha256 || !/^[0-9a-f]{64}$/.test(packed.source_sha256)) {
  throw new Error("Atlas pack manifest belongs to a different atlas");
}
const staticGroup = new THREE.Group();
scene.add(staticGroup);
const motionGroup = new THREE.Group();
scene.add(motionGroup);
const wholeGroup = new THREE.Group();
scene.add(wholeGroup);
const objects = new Map();
const motionParts = new Map();
let motion;
let scheduledFrame = 0;
let state;
let frameData;
let motionCamera;
let playback;
let plane;
let visibleParts;
let visibleLayers;
let pointerStart;
let revision = 0;
let sceneRequest = 0;
let pickTargets = [];
let composite;
let explorer;
let action = 0;
const order = new Map(Object.keys(metadata.parts).map((id, index) => [id, index]));
const loaded = new Map();
const loader = new GLTFLoader();
const whole = wholeMotion({ loader, group: wholeGroup, camera, orbit, invalidate, enter: () => {
  sceneRequest++;
  composite = undefined;
  frameData = undefined;
  stopPlayback();
  updateCompositeControls();
  explorer.identify(null);
  staticGroup.visible = false;
  motionGroup.visible = false;
  el("display").hidden = true;
  el("motion-controls").hidden = true;
  el("viewport-title").textContent = "Whole body · assisted push-up";
  el("stage-status").textContent = "Saved MuJoCo states · illustrative muscle geometry";
  el("message").textContent = "";
} });
const packOf = new Map();
for (const [file, pack] of Object.entries(packed.packs)) {
  if (!/^pack-[0-9]{2,4}(?:-[0-9]{2,4})?\.glb$/.test(file) || !/^[0-9a-f]{64}$/.test(pack.sha256) ||
      !Number.isInteger(pack.bytes) || pack.bytes < 28 || !Array.isArray(pack.parts)) {
    throw new Error("Invalid atlas pack metadata");
  }
  for (const id of pack.parts) {
    if (!order.has(id) || packOf.has(id)) throw new Error("Invalid atlas pack FJ identity");
    packOf.set(id, file);
  }
}

function loadPack(file) {
  if (loaded.has(file)) return loaded.get(file);
  const info = packed.packs[file];
  const uri = compositeEnabled ? `/api/pack/${file}/${info.sha256}` : assetDir + "packs/" + file;
  const job = loader.loadAsync(uri).then(gltf => {
    const meshes = [...gltf.scene.children];
    const names = new Set(meshes.map(o => o.name));
    const expected = info.parts;
    if (expected.length !== meshes.length || expected.some(id => !names.has(id)) ||
        meshes.some(mesh => !mesh.isMesh || !order.has(mesh.name) || objects.has(mesh.name))) {
      throw new Error("Unexpected atlas node");
    }
    for (const mesh of meshes) {
      mesh.visible = false;
      mesh.material.color.setRGB(...metadata.parts[mesh.name].color, THREE.SRGBColorSpace);
      objects.set(mesh.name, mesh);
      staticGroup.add(mesh);
    }
  }).catch(error => {
    loaded.delete(file);
    throw new Error(`Atlas asset ${file} failed to load. ${error.message}`);
  });
  loaded.set(file, job);
  return job;
}

function requiredPacks(ids) {
  return new Set(ids.filter(id => !objects.has(id)).map(id => {
    const file = packOf.get(id);
    if (!file) throw new Error(`Atlas asset for ${id} is unavailable`);
    return file;
  }));
}

function isOverview(view) {
  return view.scene === "whole-anterior" || view.scene === "whole-posterior";
}

function render() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== width || canvas.height !== height) context.setSize(width, height, false);
  camera.aspect = width / Math.max(1, height);
  camera.zoom = whole.active() ? Math.min(1, camera.aspect / 1.45) : 1;
  if (frameData) {
    camera.fov = THREE.MathUtils.radToDeg(2*Math.atan(36/(2*motionCamera.lensMm*camera.aspect)));
  }
  camera.updateProjectionMatrix();
  context.render(scene, camera);
  revision++;
}

function invalidate() {
  if (!scheduledFrame) scheduledFrame = requestAnimationFrame(() => {
    scheduledFrame = 0;
    render();
  });
}
orbit.addEventListener("change", invalidate);
new ResizeObserver(invalidate).observe(canvas);

function paint() {
  const focus = new Set(state.opaque_focus_parts ?? []);
  const overview = isOverview(state);
  const showInterior = overview && [...visibleLayers].some(layer => layer !== "skin");
  if (overview) {
    const direction = state.scene === "whole-anterior" ? "Anterior" : "Posterior";
    el("viewport-title").textContent = showInterior ? `${direction} atlas overview` : `${direction} surface`;
    el("concept-meta").textContent = `BodyParts3D · ${showInterior ? "atlas overview" : "surface preview"}`;
  }
  pickTargets = [];
  for (const [id, mesh] of objects) {
    const part = metadata.parts[id];
    mesh.visible = visibleParts.has(id) && visibleLayers.has(part.layer);
    if (!mesh.visible) continue;
    pickTargets.push(mesh);
    mesh.material.clippingPlanes = plane ? [plane] : [];
    const opacity = showInterior && part.layer === "skin" ? .18 :
      focus.size && !focus.has(id) ? state.context_opacity : 1;
    const transparent = opacity < 1;
    if (mesh.material.transparent !== transparent) {
      mesh.material.transparent = transparent;
      mesh.material.depthWrite = !transparent;
      mesh.material.side = transparent ? THREE.FrontSide : THREE.DoubleSide;
      mesh.material.needsUpdate = true;
    }
    mesh.material.opacity = opacity;
    const selected = composite ? focus.has(id) : part.identity_status !== "DISPUTED" && state.selection.includes(part.fma);
    mesh.material.emissive.setHex((composite?.core.composite_view.inspected_fj ?? state.highlighted_fj) === id ? 0x338f79 :
      selected ? 0x11372a : 0);
  }
  pickTargets.sort((a, b) => order.get(a.name) - order.get(b.name));
  invalidate();
}

function option(text, value) {
  const item = document.createElement("option");
  item.textContent = text;
  item.value = value;
  return item;
}

function getScene() {
  if (whole.active()) return whole.currentView();
  const stable = vector => vector.toArray().map(x => Number(x.toFixed(9)));
  return { ...state, visible_parts: [...visibleParts], visible_layers: [...visibleLayers],
    camera: frameData ? {frame:"mujoco-world-m", position:motionCamera.position.toArray(),
      target:motionCamera.target.toArray(), up:[0,0,1], fov_degrees:camera.fov} :
      { ...state.camera, position: stable(camera.position), target: stable(orbit.target) },
    ...(frameData ? {motion:frameData} : {}) };
}

async function setScene(value, binding) {
  const isTriplet = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
  if (value?.format !== "hmm-viewer-spike/1" || value.source_sha256 !== metadata.source_sha256 ||
      value.camera?.frame !== "packed-atlas-m" || value.motion ||
      ![value.camera.position, value.camera.target, value.camera.up].every(isTriplet) ||
      value.camera.position.every((n,i) => n === value.camera.target[i]) ||
      value.camera.up.join(",") !== "0,1,0" ||
      !(value.camera.fov_degrees >= 5 && value.camera.fov_degrees <= 100) ||
      (value.clip_plane !== null && !(Array.isArray(value.clip_plane) &&
          value.clip_plane.length === 4 && value.clip_plane.every(Number.isFinite) &&
          Math.hypot(...value.clip_plane.slice(0,3)) > 0)) ||
      !Array.isArray(value.selection) || value.selection.some(x => !/^FMA[0-9]+$/.test(x)) ||
      !Array.isArray(value.visible_layers) || value.visible_layers.some(x => typeof x !== "string") ||
      !Array.isArray(value.visible_parts) || value.visible_parts.some(x => !order.has(x)) ||
      (value.highlighted_fj != null && !value.visible_parts.includes(value.highlighted_fj))) {
    throw new Error("Invalid scene or asset identity");
  }
  const next = structuredClone(value);
  const request = ++sceneRequest;
  const required = requiredPacks(next.visible_parts);
  if (required.size) {
    el("stage-status").textContent = "Loading exact atlas parts…";
    try {
      await Promise.all([...required].map(loadPack));
    } catch (error) {
      if (request !== sceneRequest) return;
      throw error;
    }
  }
  if (request !== sceneRequest) return;
  value = next;
  whole.dispose();
  stopPlayback();
  state = value;
  composite = binding;
  frameData = undefined;
  motionGroup.visible = false;
  staticGroup.visible = true;
  orbit.enabled = true;
  camera.position.fromArray(value.camera.position);
  camera.up.fromArray(value.camera.up);
  orbit.target.fromArray(value.camera.target);
  camera.fov = value.camera.fov_degrees;
  const distance = camera.position.distanceTo(orbit.target);
  camera.near = Math.max(.001, distance * .02);
  camera.far = distance * 20 + 10;
  orbit.update();
  plane = value.clip_plane ? new THREE.Plane(
    new THREE.Vector3(...value.clip_plane.slice(0,3)).negate(), -value.clip_plane[3]).normalize() : null;
  visibleParts = new Set(value.visible_parts);
  visibleLayers = new Set(value.visible_layers);
  updateLayerControls();
  updateCompositeControls();
  if ([...el("scenes").options].some(option => option.value === value.scene)) el("scenes").value = value.scene;
  el("motion-controls").hidden = true;
  el("message").textContent = "";
  el("stage-status").textContent = composite ? "BodyParts3D · packed atlas (m)" :
    value.visible_parts.length ? "BodyParts3D · local source geometry" : "Choose a structure to load anatomy";
  el("viewport-title").textContent = composite ? el("preferred-name").textContent :
    (value.scene === "whole-anterior" ? "Anterior surface" :
      value.scene === "search" ? "Atlas selection" : value.scene.replaceAll("-", " "));
  paint();
}

function updateCompositeControls() {
  el("composite-controls").hidden = !composite;
  el("opacity-control").hidden = !composite;
  el("display").hidden = false;
  el("coverage").textContent = "";
  el("source-details").textContent = "";
  el("selection").textContent = "";
  if (!composite) {
    explorer.setConcept(null, "Choose an organ, browse a system, or tap the model to inspect a mesh.");
    explorer.identify(state?.highlighted_fj);
    return;
  }
  const { core, resolution, fjIds } = composite;
  const { concept, counts, coverage, representation, warnings } = resolution;
  el("membership").value = representation.membership_version;
  el("selection").textContent = [concept.label, concept.id, concept.side].join(" · ");
  explorer.setConcept(concept);
  const conflicts = counts.fma_conflict || counts.bp_conflict || counts.unresolved_identity;
  el("coverage-summary").dataset.conflicts = Boolean(conflicts || counts.missing_source || counts.missing_display);
  el("coverage-summary").textContent = `${counts.renderable} of ${counts.members} meshes available` +
    (conflicts ? " · Source identity differences" : "") +
    (counts.renderable < counts.members ? " · Geometry incomplete" : "");
  const details = [
    `${coverage} · ${counts.renderable}/${counts.members} FJ · ${representation.membership_version}`,
    counts.missing_source && `${counts.missing_source} missing OBJ`,
    counts.missing_display && `${counts.missing_display} missing display meshes`,
    counts.fma_conflict && `${counts.fma_conflict} FMA conflicts`,
    counts.bp_conflict && `${counts.bp_conflict} BP conflicts`,
    counts.unresolved_identity && `${counts.unresolved_identity} unresolved identities`,
    warnings.includes("version_memberships_differ") && "Version memberships differ",
  ];
  el("coverage").textContent = details.filter(Boolean).join(" · ");
  el("source-details").textContent = [
    `Catalog: ${resolution.atlas_sha256}`,
    `Display index: ${resolution.asset_manifest_sha256}`,
    ...Object.entries(resolution.source_membership_counts).map(([id,count]) => `${id} · ${count} FJ`),
  ].join("\n");
  el("isolate").textContent = core.composite_view.isolated ? "Restore context" : "Isolate";
  el("opacity").value = 100 * state.context_opacity;
  el("constituent").replaceChildren(option("Choose a mesh", ""),
    ...fjIds.map(id => option(`${id} · ${metadata.parts[id].label}`, id)));
  const id = core.composite_view.inspected_fj;
  el("constituent").value = fjIds.includes(id) ? id : "";
  explorer.identify(id, representation, concept);
}

function inspect(id) {
  if (composite) {
    composite.core.composite_view.inspected_fj = id || null;
    el("constituent").value = composite.fjIds.includes(id) ? id : "";
  } else state.highlighted_fj = id || null;
  explorer.identify(id, composite?.resolution.representation, composite?.resolution.concept);
  paint();
}

function bounds(ids) {
  const box = new THREE.Box3();
  for (const id of ids) {
    const b = metadata.parts[id].bbox;
    box.expandByPoint(new THREE.Vector3(...b.slice(0, 3)));
    box.expandByPoint(new THREE.Vector3(...b.slice(3)));
  }
  return box;
}

function focusedCamera(ids) {
  const sphere = bounds(ids).getBoundingSphere(new THREE.Sphere());
  const view = new THREE.Vector3(.24, .12, 1).normalize();
  const aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
  const distance = Math.max(.02, 1.12 * sphere.radius / (.33 * Math.min(1, aspect)));
  return { frame: "packed_atlas_m", view_asset_sha256: metadata.source_sha256, fov_axis: "vertical",
    position: sphere.center.clone().addScaledVector(view, distance).toArray(),
    target: sphere.center.toArray(), up: [0, 1, 0], fov_degrees: 40 };
}

function contextParts(ids) {
  const selected = new Set(ids);
  const sphere = bounds(ids).getBoundingSphere(new THREE.Sphere());
  return Object.values(metadata.parts).filter(p => p.layer === "bone" && packOf.has(p.fj) && !selected.has(p.fj))
    .map(p => {
      const box = bounds([p.fj]);
      return { id: p.fj, distance: box.distanceToPoint(sphere.center),
        span: box.getSize(new THREE.Vector3()).length() };
    }).filter(p => p.distance < Math.max(.10, sphere.radius * 1.2))
    .sort((a, b) => a.distance - b.distance + .28 * (b.span - a.span))
    .slice(0, 16).map(p => p.id).sort();
}

async function setComposite(core, resolution) {
  const renderable = resolution.members.filter(member => member.renderable);
  const fjIds = renderable.map(m => m.fj_id);
  if (!fjIds.length || core.selection[0] !== resolution.concept.id ||
      core.atlas_sha256 !== resolution.atlas_sha256 ||
      core.composite.selection_sha256 !== resolution.selection_sha256 ||
      core.composite.asset_manifest_sha256 !== resolution.asset_manifest_sha256 ||
      packed.source_sha256 !== resolution.source_mesh_inventory_sha256 ||
      renderable.some(m => m.pack !== packOf.get(m.fj_id) || !resolution.packs[m.pack]) ||
      Object.entries(resolution.packs).some(([file, pack]) =>
        packed.packs[file]?.sha256 !== pack.sha256 || packed.packs[file].bytes !== pack.bytes)) {
    throw new Error("Composite scene and installed asset plan differ");
  }
  const { isolated, context_fj_ids, hidden_layers, context_opacity } = core.composite_view;
  const visible = isolated ? fjIds : [...fjIds, ...context_fj_ids];
  const c = core.camera.frame === "bp3d_4_3_native_mm" ? focusedCamera(fjIds) : core.camera;
  if (c.frame !== "packed_atlas_m" || c.view_asset_sha256 !== metadata.source_sha256 || c.fov_axis !== "vertical") {
    throw new Error("Composite camera is incompatible with the installed viewer");
  }
  await setScene({ format: "hmm-viewer-spike/1", scene: "composite", source_sha256: metadata.source_sha256,
    selection: core.selection, visible_parts: visible, visible_layers: [...new Set(visible.map(id => metadata.parts[id]?.layer))].filter(layer => !hidden_layers?.includes(layer)),
    opaque_focus_parts: fjIds, context_opacity: context_opacity ?? .20, clip_plane: null, coverage: { status: resolution.coverage },
    camera: { frame: "packed-atlas-m", position: c.position, target: c.target, up: c.up, fov_degrees: c.fov_degrees },
  }, { core: structuredClone(core), resolution, fjIds });
}

function coreScene() {
  const { position, target, up, fov_degrees } = getScene().camera;
  return { ...composite.core, camera: { frame: "packed_atlas_m", view_asset_sha256: metadata.source_sha256,
    fov_axis: "vertical", position, target, up, fov_degrees } };
}

async function chooseComposite(concept, representation) {
  const token = ++action;
  sceneRequest++;
  el("message").textContent = "";
  el("stage-status").textContent = "Resolving source membership…";
  try {
    const resolution = await resolveComposite(concept, representation);
    if (token !== action) return;
    const fjIds = resolution.members.filter(m => m.renderable).map(m => m.fj_id);
    if (!fjIds.length) {
      explorer.setConcept(resolution.concept, `No renderable meshes for this source record. ${resolution.counts.members} recorded.`);
      el("composite-controls").hidden = true;
      el("coverage").textContent = `${resolution.coverage} · ${resolution.counts.members} recorded FJ`;
      el("source-details").textContent = "";
      explorer.identify(null);
      el("message").textContent = "The viewport retains the previous anatomy.";
      el("stage-status").textContent = "Previous view";
      explorer.dismissSearch();
      return;
    }
    const { scene: core } = await request("scene.create", {
      selection: [concept], representation, camera: focusedCamera(fjIds),
    });
    if (token !== action) return;
    core.composite_view.context_fj_ids = contextParts(fjIds);
    await setComposite(core, resolution);
    if (token === action) explorer.dismissSearch();
  } catch (error) {
    if (token === action) {
      el("message").textContent = error.message;
      el("stage-status").textContent = "Previous view · selection unavailable";
    }
  }
}

async function showMesh(id) {
  const token = ++action;
  if (visibleParts?.has(id) && pickTargets.some(mesh => mesh.name === id) && !frameData) {
    inspect(id);
    explorer.dismissSearch();
    return;
  }
  try {
    const part = metadata.parts[id];
    if (!part || !packOf.has(id)) throw new Error(`${id} has no installed display mesh`);
    await setScene({...searchScene, scene: "mesh", visible_parts: [id], visible_layers: [part.layer],
      highlighted_fj: id, camera: {...focusedCamera([id]), frame: "packed-atlas-m"}});
    if (token === action) {
      el("viewport-title").textContent = `Mesh ${id}`;
      explorer.dismissSearch();
    }
  } catch (error) {
    if (token === action) el("message").textContent = error.message;
  }
}

function pick(x, y) {
  const box = canvas.getBoundingClientRect();
  if (x < box.left || y < box.top || x > box.right || y > box.bottom || frameData) return [];
  ray.setFromCamera({ x: (x - box.left) * 2 / box.width - 1, y: 1 - (y - box.top) * 2 / box.height }, camera);
  const hits = ray.intersectObjects(pickTargets);
  const ids = new Set();
  for (const hit of hits) if (!plane || plane.distanceToPoint(hit.point) >= 0) ids.add(hit.object.name);
  const ordered = [...ids];
  if (isOverview(state) && visibleLayers.has("skin") && visibleLayers.size > 1) {
    return ordered.filter(id => metadata.parts[id].layer !== "skin")
      .concat(ordered.filter(id => metadata.parts[id].layer === "skin"));
  }
  return ordered;
}

function installMotion(data) {
  const ids = ["FJ1447","FJ3362","FJ3368"];
  if (!Array.isArray(data.frames) || data.frames.length !== 3 || !data.structures) throw new Error("Invalid motion artifact");
  for (const id of ids) {
    const geom = data.structures[id];
    if (!Array.isArray(geom?.vertices_mm) || !Array.isArray(geom.faces) ||
        !geom.vertices_mm.every(p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite)) ||
        !geom.faces.every(face => Array.isArray(face) && face.length === 3 &&
          face.every(i => Number.isInteger(i) && i >= 0 && i < geom.vertices_mm.length))) {
      throw new Error("Invalid motion geometry");
    }
  }
  for (const [i,frame] of data.frames.entries()) {
    if (!Number.isInteger(frame.state_index) || !Number.isFinite(frame.frame_time) ||
        (i > 0 && !(frame.frame_time > data.frames[i-1].frame_time && frame.state_index > data.frames[i-1].state_index)) ||
        !/^[a-f0-9]{64}$/.test(frame.state_sha256) ||
        !["FJ3362","FJ3368"].every(id => {
          const m = frame.transforms?.[id]?.matrix;
          return Array.isArray(m) && m.length === 4 &&
            m.every(row => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite)) &&
            m[3].join(",") === "0,0,0,1";
        }) || !Array.isArray(frame.surface?.FJ1447?.vertices_m) ||
        frame.surface.FJ1447.vertices_m.length !== data.structures.FJ1447.vertices_mm.length ||
        !frame.surface.FJ1447.vertices_m.every(p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite))) {
      throw new Error("Invalid saved frame");
    }
  }
  whole.dispose();
  for (const object of motionGroup.children) {
    object.geometry.dispose();
    object.material.dispose();
  }
  motionGroup.clear();
  motionParts.clear();
  for (const id of ids) {
    const geom = data.structures[id];
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(geom.vertices_mm.flat(), 3));
    geometry.setIndex(geom.faces.flat());
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
      color: id === "FJ1447" ? 0x9361a4 : 0xddd4bc, side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.matrixAutoUpdate = false;
    motionParts.set(id, mesh);
    motionGroup.add(mesh);
  }
  const m = data.camera;
  if (m?.lens_mm > 0 && [m.position_m,m.target_m].every(p =>
      Array.isArray(p) && p.length === 3 && p.every(Number.isFinite))) {
    motionCamera = {position:new THREE.Vector3().fromArray(m.position_m),
      target:new THREE.Vector3().fromArray(m.target_m), lensMm:m.lens_mm};
  } else throw new Error("Saved motion camera is required");
  stopPlayback();
  motion = data;
  el("frame").replaceChildren(...motion.frames.map((f,i) => option(f.phase + " · " + f.state_index, i)));
  showFrame(0);
}

function showFrame(index) {
  const f = motion?.frames[index];
  if (!f) throw new Error("Saved frame is unavailable");
  sceneRequest++;
  composite = undefined;
  updateCompositeControls();
  el("display").hidden = true;
  explorer.identify(null);
  staticGroup.visible = false;
  motionGroup.visible = true;
  el("motion-controls").hidden = false;
  el("frame").value = index;
  for (const [id, mesh] of motionParts) {
    if (f.surface[id]) {
      mesh.geometry.attributes.position.array.set(f.surface[id].vertices_m.flat());
      mesh.geometry.attributes.position.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
      mesh.geometry.computeBoundingSphere();
      mesh.geometry.computeBoundingBox();
    } else {
      mesh.matrix.set(...f.transforms[id].matrix.flat());
      mesh.matrixWorldNeedsUpdate = true;
    }
  }
  motionGroup.updateMatrixWorld(true);
  camera.up.set(0,0,1);
  camera.position.copy(motionCamera.position);
  camera.near = .01;
  camera.far = 100;
  camera.lookAt(motionCamera.target);
  orbit.enabled = false;
  frameData = { run_id: motion.run_id, state_index: f.state_index, frame_time: f.frame_time, state_sha256: f.state_sha256 };
  el("selection").textContent = "Right shoulder · exact saved frame";
  el("viewport-title").textContent = "Right shoulder · saved motion";
  el("stage-status").textContent = "MuJoCo world (m) · illustrative registration";
  el("message").textContent = f.phase + " · " + Number(f.frame_time.toFixed(3)) + " s · illustrative pectoralis";
  invalidate();
}

const scenes = Object.entries(metadata.scenes).filter(([,value]) => value.visible_parts);
const defaultScene = metadata.scenes["shoulder-elbow"]?.visible_parts ? "shoulder-elbow" : scenes[0][0];
const searchScene = { ...metadata.scenes[defaultScene], scene: "search", visible_parts: [],
  visible_layers: [], opaque_focus_parts: [], clip_plane: null };
if (compositeEnabled) {
  el("scenes").append(option("Clear viewport", "search"));
  const current = option("Selected concept", "composite");
  current.disabled = true;
  el("scenes").append(current);
}
for (const [name,value] of Object.entries(metadata.scenes)) {
  const item = option(name.replaceAll("-", " "), name);
  item.disabled = !value.visible_parts;
  el("scenes").append(item);
}
const layerNames = {artery: "Arteries", bone: "Bones", cartilage: "Cartilage", fascia: "Fascia",
  ligament: "Ligaments", muscle: "Muscles", nervous: "Nerves", organ: "Organs", skin: "Skin", vein: "Veins"};
const partsByLayer = new Map();
for (const part of Object.values(metadata.parts)) {
  if (!partsByLayer.has(part.layer)) partsByLayer.set(part.layer, []);
  if (packOf.has(part.fj)) partsByLayer.get(part.layer).push(part.fj);
}

function updateLayerControls() {
  const overview = isOverview(state);
  const available = new Set([...visibleParts].map(id => metadata.parts[id].layer));
  el("layer-scope").textContent = overview ?
    "Turn on atlas layers as needed. Skin becomes translucent over internal structures." :
    "Layers filter this scene and its visible context. Open the atlas overview to load other structures.";
  el("layer-overview").hidden = overview || !metadata.scenes["whole-anterior"]?.visible_parts;
  el("layer-status").textContent = "";
  for (const check of el("layers").querySelectorAll("input")) {
    check.checked = visibleLayers.has(check.value);
    check.disabled = overview ? !partsByLayer.get(check.value).length : !available.has(check.value);
    check.closest("label").removeAttribute("aria-busy");
  }
}

async function changeLayer(check) {
  const view = state;
  const name = check.value;
  const label = layerNames[name] ?? name;
  const status = el("layer-status");
  if (isOverview(view)) {
    const ids = partsByLayer.get(name);
    if (check.checked) {
      const row = check.closest("label");
      check.disabled = true;
      row.setAttribute("aria-busy", "true");
      status.textContent = `Loading ${label.toLowerCase()}…`;
      try {
        const results = await Promise.allSettled([...requiredPacks(ids)].map(loadPack));
        if (state !== view || frameData) return;
        const failed = results.find(result => result.status === "rejected");
        if (failed) throw failed.reason;
        for (const id of ids) visibleParts.add(id);
      } catch (error) {
        if (state === view && !frameData) {
          check.checked = false;
          status.textContent = error.message;
        }
        return;
      } finally {
        if (state === view && !frameData) {
          check.disabled = false;
          row.removeAttribute("aria-busy");
        }
      }
    } else {
      for (const id of ids) visibleParts.delete(id);
      if (view.highlighted_fj && !visibleParts.has(view.highlighted_fj)) {
        view.highlighted_fj = null;
        explorer.identify(null);
      }
    }
  }
  if (check.checked) visibleLayers.add(name);
  else visibleLayers.delete(name);
  if (composite) {
    const hidden = new Set(composite.core.composite_view.hidden_layers ?? []);
    if (check.checked) hidden.delete(name);
    else hidden.add(name);
    composite.core.composite_view.hidden_layers = [...hidden].sort();
  }
  paint();
  status.textContent = `${label} ${check.checked ? "shown" : "hidden"} · ${pickTargets.length} visible meshes`;
}

for (const name of [...partsByLayer.keys()].sort()) {
  const label = document.createElement("label");
  const check = document.createElement("input");
  check.type = "checkbox";
  check.disabled = true;
  check.value = name;
  check.addEventListener("change", () => changeLayer(check));
  label.append(check, " " + (layerNames[name] ?? name));
  el("layers").append(label);
}
el("source").textContent = metadata.dataset + " · " + Object.keys(metadata.parts).length + " source meshes · " + metadata.license;
explorer = installExplorer({ compositeEnabled, chooseComposite, showMesh, metadata });
el("membership-control").hidden = !compositeEnabled;
el("constituent").addEventListener("change", () => inspect(el("constituent").value));
el("opacity").addEventListener("input", () => {
  if (!composite) return;
  state.context_opacity = Number(el("opacity").value) / 100;
  composite.core.composite_view.context_opacity = state.context_opacity;
  paint();
});
function focusComposite() {
  if (!composite) return;
  const fitted = focusedCamera(composite.fjIds);
  camera.position.fromArray(fitted.position);
  orbit.target.fromArray(fitted.target);
  orbit.update();
  invalidate();
}
el("focus").addEventListener("click", focusComposite);
el("isolate").addEventListener("click", async () => {
  if (!composite) return;
  const token = ++action;
  const core = structuredClone(coreScene());
  core.composite_view.isolated = !core.composite_view.isolated;
  try {
    await setComposite(core, composite.resolution);
  } catch (error) {
    if (token === action) el("message").textContent = error.message;
  }
});
function setPreset() {
  const token = ++action;
  const name = el("scenes").value;
  setScene(name === "search" ? searchScene : metadata.scenes[name]).catch(error => {
    if (token === action) el("message").textContent = error.message;
  });
}
el("scenes").addEventListener("change", setPreset);
el("layer-overview").addEventListener("click", () => {
  el("scenes").value = "whole-anterior";
  setPreset();
});
el("reset").addEventListener("click", () => {
  if (whole.active()) return whole.reset();
  if (composite) return focusComposite();
  if (state.scene !== "mesh") return setPreset();
  const fitted = focusedCamera(state.visible_parts);
  camera.position.fromArray(fitted.position);
  orbit.target.fromArray(fitted.target);
  orbit.update();
});
el("export").addEventListener("click", async () => {
  let exported = getScene();
  try {
    if (whole.active()) exported = (await request("whole.set_view", { run_id: exported.run_id, view: exported })).view;
    else if (composite) exported = (await request("scene.export", { scene: coreScene() })).scene;
  } catch (error) {
    el("message").textContent = error.message;
    return;
  }
  const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "anatomy-scene.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function loadInput(input, load) {
  const file = input.files[0];
  if (!file) return;
  input.value = "";
  const token = ++action;
  sceneRequest++;
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error("Input exceeds the 5 MiB prototype limit");
    const value = JSON.parse(await file.text());
    if (token === action) await load(value, token);
  } catch (error) {
    if (token === action) el("message").textContent = error.message;
  }
}
function openCoreScene(value, token) {
  return applyCoreScene(value, {
    getScene,
    setScene: scene => token === action && setScene(scene),
    setComposite: (scene, resolved) => token === action && setComposite(scene, resolved),
    installMotion: data => token === action && installMotion(data),
    showFrame: index => token === action && showFrame(index),
  });
}
el("import").addEventListener("change", () => loadInput(el("import"), (value, token) => {
  if (value.schema_version === "hmm.anatomy.motion-view/1") {
    return whole.open(value.run_id, value, () => token === action);
  }
  if (value.schema_version !== "hmm.anatomy.scene/1") return setScene(value);
  return openCoreScene(value, token);
}));
el("motion").addEventListener("change", () => loadInput(el("motion"), installMotion));
function stopPlayback() {
  clearTimeout(playback);
  playback = undefined;
  el("play").textContent = "Play saved frames";
}
function play(index) {
  showFrame(index);
  const next = motion.frames[index + 1];
  if (!next) {
    stopPlayback();
    return;
  }
  el("play").textContent = "Pause";
  const ms = (next.frame_time - motion.frames[index].frame_time) * 1000;
  playback = setTimeout(() => play(index + 1), ms);
}
el("frame").addEventListener("change", () => {
  stopPlayback();
  showFrame(Number(el("frame").value));
});
el("play").addEventListener("click", () => {
  if (playback) stopPlayback();
  else {
    const index = Number(el("frame").value);
    play(index === motion.frames.length - 1 ? 0 : index);
  }
});
canvas.addEventListener("pointerdown", e => { pointerStart = [e.clientX,e.clientY]; });
canvas.addEventListener("pointerup", e => {
  const start = pointerStart;
  pointerStart = undefined;
  if (!start || Math.hypot(e.clientX-start[0],e.clientY-start[1]) > (e.pointerType === "touch" ? 9 : 3) || frameData || whole.active()) return;
  const id = pick(e.clientX,e.clientY)[0];
  if (id) inspect(id);
});
canvas.addEventListener("pointercancel", () => { pointerStart = undefined; });
const queryParams = new URLSearchParams(location.search);
const reviewId = queryParams.get("scene");
const startWhole = queryParams.get("motion") === "whole";
async function openInstalledWhole() {
  const token = ++action;
  el("message").textContent = "Opening saved whole-body replay…";
  try {
    const { runs } = await request("whole.discover", {});
    if (token === action) await whole.open(runs[0].run_id, null, () => token === action);
  } catch (error) {
    if (token === action) el("message").textContent = error.message;
  }
}
el("whole-open").addEventListener("click", openInstalledWhole);
el("whole-static").addEventListener("click", () => {
  el("scenes").value = "whole-anterior";
  setPreset();
});
const entry = metadata.scenes["whole-anterior"]?.visible_parts ? metadata.scenes["whole-anterior"] : metadata.scenes[defaultScene];
try {
  await setScene((startWhole || reviewId !== null && compositeEnabled) ? searchScene : entry);
} catch (error) {
  await setScene(searchScene);
  el("message").textContent = `Preview unavailable. ${error.message}`;
}
window.hmmViewer = {
  getScene, setScene, setComposite, pick, installMotion, showFrame, render,
  whole: { seek: whole.seek, status: whole.status, sample: whole.sample, matrix: whole.matrix, weights: whole.weights,
    setCamera: whole.setCamera, surfaceAudit: whole.surfaceAudit },
  visibleFjIds: () => frameData ? [...motionParts.keys()] : pickTargets.map(o => o.name),
  stats: () => ({revision, ...context.info.render}),
  project: p => {
    const v = new THREE.Vector3().fromArray(p).project(camera);
    return [(v.x+1)/2,(1-v.y)/2];
  },
  motionWorld: (id, i) => {
    const mesh = motionParts.get(id);
    return new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position,i).applyMatrix4(mesh.matrixWorld).toArray();
  },
};

if (startWhole) await openInstalledWhole();
else if (reviewId !== null) {
  const token = ++action;
  el("message").textContent = "Opening the saved review scene…";
  try {
    if (!/^(?:FMA[1-9][0-9]{0,8}|shoulder)$/.test(reviewId)) throw new Error("Unknown review scene");
    const device = matchMedia("(max-width: 700px)").matches ? "mobile" : "desktop";
    const file = reviewId === "shoulder" ? reviewId : `${reviewId}-${device}`;
    const response = await fetch(`./review-scenes/${file}.json`);
    if (!response.ok) throw new Error("The saved review scene is unavailable");
    const reviewed = await response.json();
    if (token === action) await openCoreScene(reviewed, token);
  } catch (error) {
    if (token === action) el("message").textContent = error.message;
  }
}
