import * as THREE from "three";
import { OrbitControls } from "./npm/node_modules/three/examples/jsm/controls/OrbitControls.js";

const schema = "hmm.registration-annotations/2";
const identityKeys = ["source_fj_id", "source_fma_id", "source_bp_id", "source_sha256", "target_geom",
  "target_mesh_sha256", "source_model_sha256", "anatomy_revision", "geometry_sha256", "side",
  "source_frame", "target_frame"];
const fileLimit = 1 << 20;

export function landmarkEditor(container, refreshOverlay) {
  const section = document.createElement("details");
  section.className = "landmark-editor";
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "./landmark_editor.css";
  document.head.append(css);
  section.innerHTML = `<summary>Named landmark annotation · operator candidates</summary>
    <p data-pin></p><pre data-transform></pre>
    <p>Axes in the selected native frame: red +X, green +Y, blue +Z. Model side follows the pinned bone.
       Click or tap the surface to place or adjust the point. Drag to orbit. Scroll or pinch to zoom.</p>
    <label>Coordinate frame <select data-side><option value="source">BodyParts3D OBJ mm</option>
      <option value="target">MuJoCo compiled geom-local m</option></select></label>
    <div data-stage></div>
    <p data-coordinates></p>
    <form>
    <label>Landmark <select name="landmark"></select></label>
    <label>Role <select name="role"><option>FIT</option><option>HELD_OUT</option></select></label>
    <label>Uncertainty (mm) <input name="uncertainty" type="number" min="0" step="any" required></label>
    <label>Reviewer ID as supplied <input name="reviewer" maxlength="256" required></label>
    <label>Source citation (HTTPS) <input name="citation" type="url" maxlength="256" required></label>
    <button type="submit">Append candidate</button>
    <button type="button" data-withdraw>Withdraw selected landmark</button>
    <label>Prior version <select data-history></select></label>
    <button type="button" data-restore>Restore selected version</button>
    </form>
    <p><button data-save>Export annotation history</button>
      <label>Reopen annotation history <input data-load type="file" accept=".json,application/json"></label></p>
    <p data-message role="status"></p>`;
  section.hidden = true;
  container.append(section);
  const pick = q => section.querySelector(q);
  const form = pick("form"), scope = form.elements, message = pick("[data-message]");
  const side = pick("[data-side]"), stage = pick("[data-stage]");
  let log = {schema_version: schema, correspondences: [], decisions: [], footprints: []};
  let pair, names = [], mesh, view, points = {}, generation = 0, known = new Map();
  const files = new Map();
  const keyFor = c => `${c.source_fj_id}/${c.target_geom}`;
  const same = (a, b) => identityKeys.every(key => a[key] === b[key]);
  const last = id => log.decisions.findLast(d => d.correspondence_id === id);
  const anchorFits = (mesh, xyz, anchor, tolerance) => {
    const indices = mesh?.triangles[anchor?.face];
    if (!indices || !xyz) return false;
    const v = indices.map(i => new THREE.Vector3(...mesh.vertices[i]));
    if (v[1].clone().sub(v[0]).cross(v[2].clone().sub(v[0])).lengthSq() < (tolerance * tolerance * 1e-6) ** 2)
      return false;
    const reconstructed = v.reduce((sum, point, i) => sum.addScaledVector(point, anchor.weights[i]),
      new THREE.Vector3());
    return reconstructed.distanceTo(new THREE.Vector3(...xyz)) <= tolerance;
  };
  const fits = c => anchorFits(mesh?.source, c.source_mm, c.source_anchor, .05) &&
    anchorFits(mesh?.target, c.target_geom_m, c.target_anchor, .00005);
  const active = () => pair ? log.correspondences.filter(c => same(c, pair) && fits(c)
    && last(c.id)?.decision === "USE_FOR_COMPARISON") : [];

  function coordinates() {
    pick("[data-coordinates]").textContent = ["source", "target"].map((key, i) =>
      `${i ? "Target (m)" : "Source (mm)"}: ${points[key]?.xyz.map(v => v.toFixed(i ? 6 : 3)).join(", ") ?? "pending"}`
    ).join(" · ");
    refreshOverlay();
  }

  function showView() {
    if (!mesh || !section.open) return;
    if (!view) {
      const renderer = new THREE.WebGLRenderer({antialias: true});
      renderer.setSize(360, 280, false);
      renderer.domElement.setAttribute("aria-label", "Pinned annotation surface");
      stage.append(renderer.domElement);
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x202733);
      const camera = new THREE.PerspectiveCamera(38, 360 / 280, .0001, 10000);
      camera.up.set(0, 0, 1);
      const orbit = new OrbitControls(camera, renderer.domElement);
      orbit.addEventListener("change", () => renderer.render(scene, camera));
      let start;
      renderer.domElement.addEventListener("pointerdown", event => {
        start = [event.clientX, event.clientY];
      });
      renderer.domElement.addEventListener("pointerup", event => {
        if (!start || Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 5) return;
        start = undefined;
        const box = renderer.domElement.getBoundingClientRect(), ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2(2 * (event.clientX - box.left) / box.width - 1,
          1 - 2 * (event.clientY - box.top) / box.height), camera);
        const hit = ray.intersectObject(view.surface)[0];
        if (!hit) return;
        const {vertices, triangles} = mesh[side.value];
        const triangle = triangles[hit.faceIndex].map(i => new THREE.Vector3(...vertices[i]));
        const weights = THREE.Triangle.getBarycoord(hit.point, ...triangle, new THREE.Vector3())
          ?.toArray().map(w => Math.max(0, Math.min(w, 1)));
        if (!weights) return;
        const sum = weights.reduce((a, b) => a + b);
        points[side.value] = {xyz: hit.point.toArray(), anchor: {face: hit.faceIndex, weights: weights.map(w => w / sum)}};
        showPoint();
        coordinates();
      });
      view = {renderer, scene, camera, orbit};
    }
    const {renderer, scene, camera, orbit} = view;
    for (const obj of [...scene.children]) {
      obj.geometry.dispose();
      obj.material.dispose();
      obj.removeFromParent();
    }
    const {vertices, triangles} = mesh[side.value];
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(vertices.flat(), 3));
    geo.setIndex(triangles.flat());
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    const {center, radius} = geo.boundingSphere;
    const surface = new THREE.Mesh(geo, new THREE.MeshNormalMaterial({side: THREE.DoubleSide}));
    scene.add(surface, new THREE.AxesHelper(radius * .75));
    // The axes show native directions from the mesh centre.
    scene.children[1].position.copy(center);
    orbit.target.copy(center);
    const direction = new THREE.Vector3(1, -1, .8).normalize();
    const defaultPosition = center.clone().addScaledVector(direction, radius * 2.7);
    // Prefer an actual visible triangle in the central view when the bone is strongly concave.
    const positions = geo.getAttribute("position");
    const centreVertex = vertices.reduce((best, xyz, i) =>
      new THREE.Vector3(...xyz).distanceToSquared(center) <
      new THREE.Vector3(...vertices[best]).distanceToSquared(center) ? i : best, 0);
    orbit.target.fromBufferAttribute(positions, centreVertex);
    camera.position.copy(defaultPosition);
    camera.up.set(0, 0, 1);
    camera.near = radius / 100;
    camera.far = radius * 100;
    camera.updateProjectionMatrix();
    scene.updateMatrixWorld(true);
    view.surface = surface;
    view.dot = new THREE.Mesh(new THREE.SphereGeometry(radius * .025),
      new THREE.MeshBasicMaterial({color: 0xffffff, depthTest: false}));
    scene.add(view.dot);
    orbit.update();
    stage.dataset.camera = JSON.stringify({frame:side.value, position:camera.position.toArray(),
      target:orbit.target.toArray(), up:camera.up.toArray(), fov:camera.fov});
    showPoint();
  }

  function showPoint() {
    const point = points[side.value];
    if (view?.dot) {
      view.dot.visible = Boolean(point);
      if (point) view.dot.position.fromArray(point.xyz);
      view.renderer.render(view.scene, view.camera);
    }
  }

  function historyOptions() {
    const withdrawn = pair ? log.correspondences.filter(c => same(c, pair) && c.name === scope.landmark.value
      && last(c.id)?.decision === "WITHDRAW") : [];
    pick("[data-history]").replaceChildren(...withdrawn.map(c =>
      new Option(last(c.id).time + " · " + c.id.slice(0, 8), c.id)));
  }

  function selectLandmark() {
    historyOptions();
    const item = active().find(c => c.name === scope.landmark.value);
    points = item ? {source: {xyz: item.source_mm, anchor: item.source_anchor},
      target: {xyz: item.target_geom_m, anchor: item.target_anchor}} : {};
    if (item) {
      scope.role.value = item.role;
      scope.uncertainty.value = item.uncertainty_mm;
      scope.citation.value = item.source_evidence;
    } else {
      scope.role.value = names.indexOf(scope.landmark.value) < 3 ? "FIT" : "HELD_OUT";
      scope.uncertainty.value = "";
      scope.citation.value = pair?.geometry.source_citation ?? "";
    }
    showPoint();
    coordinates();
  }

  async function loadMesh() {
    if (!pair || !section.open || mesh) return;
    const id = ++generation, {sha256, bytes} = pair.geometry;
    try {
      if (!/^[a-f0-9]{64}$/.test(sha256) || bytes > 4 << 20) throw new Error("Invalid pinned mesh identity");
      if (!files.has(sha256)) {
        const response = await fetch(`/landmark-mesh/${sha256}.json`);
        if (!response.ok) throw new Error("Pinned local mesh unavailable");
        const raw = await response.arrayBuffer();
        const sha = new Uint8Array(await crypto.subtle.digest("SHA-256", raw));
        const hash = Array.from(sha, b => b.toString(16).padStart(2, "0")).join("");
        if (hash !== sha256 || raw.byteLength !== bytes) throw new Error("Pinned local mesh differs");
        files.set(sha256, JSON.parse(new TextDecoder().decode(raw)));
      }
      if (id !== generation) return;
      mesh = files.get(sha256);
      stage.hidden = false;
      selectLandmark();
      showView();
      message.textContent = "Pinned triangle meshes loaded.";
    } catch (error) {
      if (id === generation) message.textContent = error.message;
    }
  }

  function bound(candidate, landmarks) {
    if (candidate?.geometry) known.set(keyFor(candidate), candidate);
    section.hidden = !candidate?.geometry;
    if (candidate && pair && same(candidate, pair)) return;
    generation++;
    pair = candidate?.geometry ? candidate : undefined;
    mesh = undefined;
    stage.hidden = true;
    if (!pair) return;
    names = landmarks.map(m => m.name);
    scope.landmark.replaceChildren(...names.map(n => new Option(n, n)));
    pick("[data-pin]").textContent =
      `${pair.side} · ${pair.source_fj_id} / ${pair.source_bp_id} / ${pair.source_fma_id} · ${pair.target_geom}\n` +
      `Source: ${pair.geometry.source_revision} · target: ${pair.geometry.target_revision}`;
    pick("[data-transform]").textContent =
      `Archived ICP, source OBJ mm → compiled geom-local m (row-major; proper 0.001 scale)\n` +
      pair.archived_icp.source_mm_to_native_geom_m.map(row => row.map(x => x.toPrecision(5)).join("  ")).join("\n");
    message.textContent = "";
    selectLandmark();
    void loadMesh();
  }

  function decision(id, value) {
    const reviewer = scope.reviewer.value.trim();
    if (!reviewer || log.decisions.length >= 600) throw new Error("Reviewer ID and history capacity required");
    log.decisions.push({id: crypto.randomUUID(), correspondence_id: id, reviewer,
      evidence: "Operator action in Registration Evidence Inspector", time: new Date().toISOString(),
      decision: value, supersedes: last(id)?.id ?? null});
  }

  const duplicates = (candidate, prior) => active().some(c => c !== prior &&
    (Math.hypot(...c.source_mm.map((v, i) => v - candidate.source_mm[i])) <= .05 ||
     Math.hypot(...c.target_geom_m.map((v, i) => v - candidate.target_geom_m[i])) <= .00005));

  form.addEventListener("submit", event => {
    event.preventDefault();
    try {
      if (!pair || !mesh || !points.source || !points.target) throw new Error("Place both points on pinned surfaces");
      if (!scope.citation.value.startsWith("https://") || !scope.reviewer.value.trim())
        throw new Error("HTTPS citation and reviewer ID are required");
      const prior = active().find(c => c.name === scope.landmark.value);
      if (log.correspondences.length >= 300 || log.decisions.length + (prior ? 2 : 1) > 600)
        throw new Error("Annotation history is full");
      const id = crypto.randomUUID();
      const candidate = {...Object.fromEntries(identityKeys.map(k => [k, pair[k]])),
        id, name: scope.landmark.value, role: scope.role.value, method: "OPERATOR_SURFACE_PICK",
        source_evidence: scope.citation.value, uncertainty_mm: Number(scope.uncertainty.value),
        source_mm: points.source.xyz, target_geom_m: points.target.xyz,
        source_anchor: points.source.anchor, target_anchor: points.target.anchor};
      if (duplicates(candidate, prior))
        throw new Error("Duplicate active point or fit/held-out overlap");
      if (prior) decision(prior.id, "WITHDRAW");
      log.correspondences.push(candidate);
      decision(id, "USE_FOR_COMPARISON");
      message.textContent = "Operator candidate appended. Export and validate with the registration CLI.";
      historyOptions();
      refreshOverlay();
    } catch (error) {
      message.textContent = error.message;
    }
  });

  pick("[data-withdraw]").onclick = () => {
    try {
      const prior = active().find(c => c.name === scope.landmark.value);
      if (!prior) throw new Error("No active candidate for this landmark");
      decision(prior.id, "WITHDRAW");
      selectLandmark();
      message.textContent = "Withdrawal appended.";
    } catch (error) {
      message.textContent = error.message;
    }
  };
  pick("[data-restore]").onclick = () => {
    try {
      if (!pair || active().some(c => c.name === scope.landmark.value))
        throw new Error("Withdraw the active version first");
      const prior = log.correspondences.find(c => same(c, pair) && c.id === pick("[data-history]").value);
      if (prior && (!fits(prior) || duplicates(prior))) throw new Error("Duplicate active point or fit/held-out overlap");
      if (!prior) throw new Error("No previous version");
      decision(prior.id, "USE_FOR_COMPARISON");
      selectLandmark();
      message.textContent = "Restoration appended.";
    } catch (error) {
      message.textContent = error.message;
    }
  };
  pick("[data-save]").onclick = () => {
    const blob = new Blob([JSON.stringify(log, null, 2)], {type: "application/json"});
    if (blob.size > fileLimit) { message.textContent = "Annotation file exceeds 1 MiB."; return; }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "landmark-annotations.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  pick("[data-load]").onchange = async event => {
    try {
      const [file] = event.target.files;
      if (!file || file.size > fileLimit) throw new Error("Annotation file exceeds 1 MiB");
      if (log.decisions.length && !window.confirm("Replace the open history? Export it first to retain local edits.")) return;
      const imported = JSON.parse(await file.text());
      if (imported.schema_version !== schema || !Array.isArray(imported.correspondences) ||
          !Array.isArray(imported.decisions) || !Array.isArray(imported.footprints) || imported.footprints.length ||
          imported.correspondences.length > 300 || imported.decisions.length > 600)
        throw new Error("Unsupported annotation history");
      const ids = new Set(imported.correspondences.map(c => c.id)), decisions = new Set(), latest = new Map();
      for (const c of imported.correspondences) {
        const pinned = known.get(keyFor(c));
        const frame = (point, anchor) => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite)
          && anchor && Number.isInteger(anchor.face) && anchor.face >= 0 &&
          Array.isArray(anchor.weights) && anchor.weights.length === 3 &&
          anchor.weights.every(w => Number.isFinite(w) && w >= 0 && w <= 1) &&
          Math.abs(anchor.weights.reduce((a, b) => a + b) - 1) < 1e-6;
        if ((pinned && !same(c, pinned)) || !["FIT", "HELD_OUT"].includes(c.role) ||
            !c.source_evidence?.startsWith("https://") ||
            (c.source_mm != null || c.target_geom_m != null) &&
            (!frame(c.source_mm, c.source_anchor) || !frame(c.target_geom_m, c.target_anchor)))
          throw new Error("Invalid coordinates, identity or frame in reopened history");
        if (c.source_mm != null && pair && same(c, pair) && mesh && !fits(c))
          throw new Error("Point is not on its pinned triangle");
        if (c.source_mm != null && (c.method !== "OPERATOR_SURFACE_PICK" ||
            !Number.isFinite(c.uncertainty_mm) || c.uncertainty_mm < 0))
          throw new Error("Point provenance or uncertainty is missing");
      }
      for (const d of imported.decisions) {
        if (!ids.has(d.correspondence_id) || decisions.has(d.id) ||
            (d.supersedes ?? null) !== (latest.get(d.correspondence_id) ?? null) ||
            !["USE_FOR_COMPARISON", "REJECT", "WITHDRAW"].includes(d.decision))
          throw new Error("Invalid decision history");
        decisions.add(d.id);
        latest.set(d.correspondence_id, d.id);
      }
      if (ids.size !== imported.correspondences.length ||
          imported.correspondences.some(c => c.source_mm != null && !latest.has(c.id)))
        throw new Error("Annotation IDs or decisions are incomplete");
      log = imported;
      selectLandmark();
      message.textContent = "History reopened as operator candidates. CLI validation is required before installation.";
    } catch (error) {
      message.textContent = error.message;
    } finally {
      event.target.value = "";
    }
  };
  section.addEventListener("toggle", () => void loadMesh());
  side.addEventListener("change", showView);
  scope.landmark.addEventListener("change", selectLandmark);
  return {bound, active};
}
