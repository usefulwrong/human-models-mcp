import * as THREE from "three";
import { landmarkEditor } from "./landmark_editor.js";
import { request } from "./lab_bridge.js";

const gltf = ([x, y, z]) => new THREE.Vector3(x, z, -y);

export function registrationPanel({ after, root, nodes, invalidate }) {
  const details = document.createElement("details");
  details.id = "registration-evidence";
  details.hidden = true;
  const summary = document.createElement("summary");
  summary.textContent = "Registration evidence";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const boneSelect = document.createElement("select");
  boneSelect.setAttribute("aria-label", "Bone candidate");
  const rows = document.createElement("ul");
  details.append(summary, status, boneSelect, rows);
  after.after(details);
  const markers = new THREE.Group();
  markers.name = "Registration evidence overlay";
  let token = 0, fields, activeKey, current;
  const editor = landmarkEditor(details, overlay);
  const pairsFor = () => current?.bones?.flatMap(b => b.alternatives.map(c => [b, c])) ?? [];
  function bindEditor() {
    const selected = pairsFor()[boneSelect.selectedIndex];
    editor.bound(selected?.[1], selected?.[0].named_landmarks);
  }

  function clearMarkers() {
    markers.removeFromParent();
    for (const child of [...markers.children]) {
      child.geometry.dispose();
      child.material.dispose();
      markers.remove(child);
    }
    invalidate();
  }

  function add(points, color, size, line = false) {
    if (!points.length) return;
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const common = {color, depthTest: false, depthWrite: false};
    const object = line ? new THREE.Line(geometry, new THREE.LineBasicMaterial(common)) :
      new THREE.Points(geometry, new THREE.PointsMaterial({...common, size, sizeAttenuation: false}));
    object.renderOrder = 20;
    markers.add(object);
  }

  function overlay() {
    clearMarkers();
    if (!current?.pilot || !details.open || !root()) return;
    root().add(markers);
    const route = current.routes.find(r => r.name === current.pilot.native_route) ?? current.routes[0];
    if (route) {
      add(route.wrap_polyline_world_m.map(gltf), 0x38dcff, 0, true);
      add(route.model_sites_world_m.map(gltf), 0x38dcff, 9);
    }
    const pair = pairsFor()[boneSelect.selectedIndex];
    if (pair) {
      const [bone, candidate] = pair;
      const target = nodes.get(bone.native.node);
      if (target) {
        target.updateWorldMatrix(true, false);
        const pose = new THREE.Matrix4().copy(root().matrixWorld).invert().multiply(target.matrixWorld);
        const world = p => gltf(p).applyMatrix4(pose);
        const atlasToGeom = new THREE.Matrix4().set(...candidate.archived_icp.source_mm_to_native_geom_m.flat());
        add(candidate.atlas_preview_geom_m.map(world), 0xdaa6ff, 3);
        add(candidate.markers.filter(m => m.role === "FIT").map(m => world(m.target_geom_m)), 0xffd467, 9);
        add(candidate.markers.filter(m => m.role === "HELD_OUT").map(m => world(m.target_geom_m)), 0xff825e, 10);
        const installed = candidate.annotations ?? [];
        const local = editor.active();
        const named = [...installed.filter(p => !local.some(c => c.name === p.name)), ...local];
        for (const annotation of named) {
          const a = world(new THREE.Vector3(...annotation.source_mm).applyMatrix4(atlasToGeom).toArray());
          const b = world(annotation.target_geom_m);
          add([a, b], 0xf3f2ef, 0, true);
          add([a], 0xda82ff, 9);
          add([b], 0xffffff, 9);
        }
        for (const area of current.pilot.candidate_footprints.filter(p => p.source_fj_id === candidate.source_fj_id)) {
          const polygon = area.polygon_mm.map(p => world(new THREE.Vector3(...p).applyMatrix4(atlasToGeom).toArray()));
          add([...polygon, polygon[0]], 0x96e691, 0, true);
        }
      }
    }
    invalidate();
  }

  function render(value) {
    current = value;
    rows.replaceChildren();
    boneSelect.hidden = !value.pilot;
    if (!value.pilot) {
      bindEditor();
      status.textContent = value.status;
      return;
    }
    const prior = boneSelect.value;
    const {pilot, bones} = value;
    status.textContent = `#${value.frame.state_index} · ${pilot.display_name} · ${pilot.association} · anatomy ${value.status}`;
    const pairs = bones.flatMap(b => b.alternatives);
    boneSelect.replaceChildren(...pairs.map(c => new Option(`${c.side} · ${c.target_geom} / ${c.source_fj_id}`, c.source_fj_id)));
    if (pairs.some(c => c.source_fj_id === prior)) boneSelect.value = prior;
    boneSelect.hidden = !pairs.length;
    function item(text) {
      const li = document.createElement("li");
      li.textContent = text;
      rows.append(li);
    }
    if (pilot.atlas_surface) {
      const source = value.sources.sources.find(s => s.id === pilot.atlas_surface.source_id);
      item(`BodyParts3D · ${pilot.atlas_surface.fj_id} · ${pilot.atlas_surface.fma_id} · ${source?.license ?? "see source matrix"}`);
    }
    item(`Moving surface · ${pilot.visual_surface.dataset} · ${pilot.visual_surface.mesh_id}`);
    if (pilot.textual_reference) {
      const t = pilot.textual_reference;
      item(`Candidate attachment regions · ${t.origin_region} → ${t.insertion_region} · DBCLS workbook row ${t.list_row}`);
    }
    if (value.routes.length) item(`Cyan · model route/sites · ${value.routes.map(r => r.name).join(", ")}`);
    if (pairs.length) item("Purple · sampled atlas bone (archived ICP) · yellow · fit proxies · orange · held-out proxies");
    if (pairs.some(c => c.geometry)) item("GEOMETRIC_PROXY / CANDIDATE · named annotations are operator candidates (white target; pink source; line connects the pair).");
    if (pilot.candidate_footprints.length) item("Green · manually annotated candidate footprint boundary");
    for (const b of bones) {
      item(`${b.catalog_label} · ${b.reason ?? b.status} · named landmarks: ${b.named_landmarks.map(m => m.name).join(", ")}`);
      for (const c of b.alternatives) {
        const icp = c.methods.icp_held_out.held_out_rms_mm;
        const rigid = c.methods.axis_extrema_rigid.held_out_rms_mm;
        const manual = c.manual_named_landmark_rigid.held_out_rms_mm;
        item(`${c.source_fj_id} ${c.source_fma_id} · ${c.status} · geometric held-out RMS · ICP ${icp.toFixed(1)} mm · extrema rigid ${rigid?.toFixed(1) ?? "inconclusive"} mm${manual === undefined ? "" : ` · manual named candidate ${manual.toFixed(1)} mm`}`);
      }
    }
    for (const problem of value.blockers) item(`${problem.status} · ${problem.missing}`);
    bindEditor();
    overlay();
  }

  function update(next) {
    fields = next;
    details.hidden = !fields;
    const key = fields && details.open ? JSON.stringify(fields) : null;
    if (key === activeKey) return;
    activeKey = key;
    const requestId = ++token;
    current = undefined;
    clearMarkers();
    rows.replaceChildren();
    boneSelect.hidden = true;
    status.textContent = key ? "Loading exact saved-frame evidence…" : "";
    if (!key) { bindEditor(); return; }
    request("muscle.registration", {...fields, evidence_frame: "mujoco_world_m"}).then(value => {
      if (requestId === token) render(value.evidence ?? {status: "NOT_INSTALLED"});
    }).catch(error => {
      if (requestId === token) status.textContent = error.message;
    });
  }

  details.addEventListener("toggle", () => update(fields));
  boneSelect.addEventListener("change", () => { bindEditor(); overlay(); });
  return {update, clear: () => update(null)};
}
