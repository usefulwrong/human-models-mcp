import * as THREE from "three";
import { request } from "./lab_bridge.js";

export function wholeMotion({ loader, group, camera, orbit, invalidate, enter }) {
  const el = id => document.getElementById(id);
  const timeline = el("whole-timeline");
  const layerPanel = el("whole-layers");
  const controls = el("whole-controls");
  const contact = document.createElement("details");
  contact.hidden = true;
  const contactTitle = document.createElement("summary");
  contactTitle.textContent = "Experimental contact evidence";
  const contactGate = document.createElement("p");
  const contactMethod = document.createElement("details");
  const contactMethodTitle = document.createElement("summary");
  contactMethodTitle.textContent = "Interpretation and better estimates";
  const contactInterpretation = document.createElement("p");
  contactMethod.append(contactMethodTitle, contactInterpretation);
  const contactPart = document.createElement("select");
  contactPart.setAttribute("aria-label", "Contact part");
  contactPart.append(new Option("Right hand", "hand_r"), new Option("Left hand", "hand_l"));
  const contactButton = document.createElement("button");
  contactButton.type = "button";
  contactButton.textContent = "Read saved contact";
  const contactValue = document.createElement("p");
  contactValue.setAttribute("role", "status");
  contactValue.style.overflowWrap = "anywhere";
  contact.append(contactTitle, contactGate, contactPart, contactButton, contactValue, contactMethod);
  layerPanel.after(contact);
  contactButton.addEventListener("click", async () => {
    const clipRun = run, frame = run.frames[index], part = contactPart.value;
    contactValue.textContent = "Reading saved contact…";
    try {
      const result = await request("whole.contact", { run_id: clipRun.run_id, part, sample: frame.state_index });
      if (run !== clipRun || run.frames[index] !== frame || contactPart.value !== part) return;
      const info = result.scientific_quantity;
      const d = result.scenario_diagnostics;
      const force = info.quantities.total_normal_force_N;
      const pressure = info.quantities.skin_contact_pressure;
      contactValue.textContent = [
        `Saved state #${result.sample} · ${result.time_s.toFixed(3)} s · ${result.measurement_status}`,
        `Proxy normal-force sum ${result.total_normal_force_N.toPrecision(6)} ${force.unit}`,
        `Skin pressure: ${result.skin_contact_pressure.status}`,
        d.max_support_slip_m && `Run maximum support drift ${(1000 * d.max_support_slip_m.value).toFixed(2)} mm`,
        d.max_hinge_limit_violation_rad && `Maximum hinge-limit violation ${d.max_hinge_limit_violation_rad.value.toPrecision(4)} rad`,
        d.external_work_J && `External work ${d.external_work_J.value.toFixed(2)} J`,
      ].filter(Boolean).join(" · ");
      contactInterpretation.textContent = [
        force.definition, force.improve_estimate, pressure.improve_estimate,
        `Human experimental validation: ${info.human_validation}.`,
        `Run ${result.run_id} · State SHA-256 ${result.state_sha256} · Contact manifest SHA-256 ${info.sources_sha256["contact_manifest.json"]}`,
      ].join(" ");
    } catch (error) {
      if (run === clipRun && run.frames[index] === frame) contactValue.textContent = error.message;
    }
  });
  function clearContact() {
    contactValue.textContent = contactInterpretation.textContent = "";
    contactMethod.open = false;
  }
  contactPart.addEventListener("change", clearContact);
  let clip, mixer, action, rig, run, layers, index, cameraName, motionSha;
  let pending = 0;
  let started, offset, clock = 0;
  const nodes = new Map();
  const scratch = new THREE.Vector3();

  function currentView() {
    return {
      schema_version: "hmm.anatomy.motion-view/1", run_id: run.run_id, motion_sha256: motionSha,
      state_index: run.frames[index].state_index, layers: [...layers],
      camera: { position: camera.position.toArray(), target: orbit.target.toArray(), fov: camera.fov },
    };
  }

  function pose(time) {
    clock = time;
    action.paused = false;
    action.enabled = true;
    mixer.setTime(time);
    rig.updateMatrixWorld(true);
    invalidate();
  }

  function readout(exact) {
    const frame = run.frames[index];
    if (contactValue.dataset.sample !== String(index)) {
      clearContact();
      contactValue.dataset.sample = index;
    }
    timeline.value = index;
    el("whole-time").textContent = exact ?
      `#${frame.state_index} · ${frame.frame_time.toFixed(2)} s · ${frame.phase}` :
      `${(clock + run.frames[0].frame_time).toFixed(2)} s · interpolated pose · saved sample #${frame.state_index}`;
    if (run.contact && layers.has("OVERLAYS")) {
      const distances = Object.entries(frame.min_surface_distance_m).map(([part, value]) =>
        `${part} ${(1000 * value).toFixed(2)} mm`);
      el("whole-time").textContent += ` · ${frame.floor_contact_count} loaded contacts · ${distances.join(" · ")}`;
    }
  }

  function pause() {
    cancelAnimationFrame(pending);
    pending = 0;
    el("whole-play").textContent = "Play";
  }

  function seek(next) {
    if (!Number.isInteger(next) || !run?.frames[next]) throw new Error("Saved frame unavailable");
    pause();
    index = next;
    pose(run.frames[index].frame_time - run.frames[0].frame_time);
    readout(true);
  }

  function animate(now) {
    started ??= now;
    const seconds = offset + (now - started) / 1000 * Number(el("whole-speed").value);
    if (seconds >= run.frames.at(-1).frame_time - run.frames[0].frame_time) {
      seek(run.frames.length - 1);
      return;
    }
    while (index + 1 < run.frames.length &&
           run.frames[index + 1].frame_time - run.frames[0].frame_time <= seconds) index++;
    pose(run.contact ? run.frames[index].frame_time - run.frames[0].frame_time : seconds);
    readout(Boolean(run.contact));
    pending = requestAnimationFrame(animate);
  }

  function setCamera(value) {
    camera.position.fromArray(value.position);
    orbit.target.fromArray(value.target);
    camera.up.set(0, 1, 0);
    camera.fov = value.fov;
    camera.near = .015;
    camera.far = 30;
    orbit.enabled = true;
    orbit.update();
    invalidate();
  }

  function showLayers() {
    rig.traverse(o => {
      if (o.userData.layer) o.visible = layers.has(o.userData.layer);
    });
    invalidate();
  }

  function dispose() {
    pause();
    controls.hidden = true;
    contact.hidden = true;
    contactValue.textContent = "";
    layerPanel.hidden = true;
    if (rig) {
      mixer.stopAllAction();
      mixer.uncacheRoot(rig);
      const disposed = new Set();
      rig.traverse(o => {
        for (const item of [o.geometry, o.material, o.skeleton]) {
          if (item && !disposed.has(item)) {
            item.dispose();
            disposed.add(item);
          }
        }
      });
      group.remove(rig);
      rig = undefined;
      nodes.clear();
    }
  }

  async function open(runId, view, isCurrent) {
    const result = await request("whole.open", { run_id: runId });
    const candidate = result.motion;
    let chosen;
    if (view) chosen = (await request("whole.set_view", { run_id: runId, view })).view;
    const artifact = candidate.artifacts["motion.glb"];
    const response = await fetch(`/api/whole/motion.glb/${artifact.sha256}`);
    if (!response.ok) throw new Error("Verified whole-body asset unavailable");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== artifact.bytes) throw new Error("Motion asset size mismatch");
    // Plain LAN HTTP has no Web Crypto. The server hashes the stream before sending this header.
    const hash = crypto.subtle
      ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        b => b.toString(16).padStart(2, "0")).join("")
      : response.headers.get("X-HMM-SHA256");
    if (hash !== artifact.sha256) throw new Error("Motion asset SHA-256 mismatch");
    if (!isCurrent()) return;
    const gltf = await loader.parseAsync(bytes, "");
    if (!isCurrent()) {
      gltf.scene.traverse(o => {
        o.geometry?.dispose();
        o.material?.dispose();
        o.skeleton?.dispose();
      });
      return;
    }
    dispose();
    enter();
    run = candidate;
    motionSha = result.motion_sha256;
    rig = gltf.scene;
    group.add(rig);
    rig.traverse(o => {
      const id = gltf.parser.associations.get(o)?.nodes;
      if (id !== undefined) nodes.set(id, o);
      if (o.isSkinnedMesh) o.frustumCulled = false;
    });
    clip = gltf.animations[0];
    mixer = new THREE.AnimationMixer(rig);
    action = mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 0);
    action.clampWhenFinished = true;
    action.play();
    timeline.max = run.frames.length - 1;
    layers = new Set(chosen?.layers ?? run.default_layers);
    el("whole-layer-options").replaceChildren(...Object.entries(run.layers).filter(([name]) => name !== "BODY")
      .map(([name, layer]) => {
        const label = document.createElement("label");
        const check = document.createElement("input");
        check.type = "checkbox";
        check.value = name;
        check.disabled = !layer.available;
        check.checked = layers.has(name);
        check.addEventListener("change", () => {
          if (check.checked) layers.add(name);
          else layers.delete(name);
          showLayers();
          readout(!pending || Boolean(run.contact));
        });
        const title = { SKELETON: "Skeleton", MUSCLES: "Muscles", ORGANS: "Organs · static atlas",
          SKIN: "Skin · static atlas", OVERLAYS: candidate.contact ? "Debug contacts" : "Contact pads" }[name];
        label.append(check, " " + title);
        label.title = layer.description;
        return label;
      }));
    cameraName = run.default_camera;
    el("whole-camera").value = cameraName;
    setCamera(chosen?.camera ?? run.cameras[cameraName]);
    controls.hidden = false;
    contact.hidden = !run.contact;
    clearContact();
    contactTitle.textContent = run.contact ? `Experimental contact evidence · ${run.acceptance.full_pushup}` :
      "Experimental contact evidence";
    if (run.contact) {
      const label = run.scenario_id === "pushup_flat_palm" ? "Experimental flat-palm contact" : "Experimental palm contact";
      el("viewport-title").textContent = `${label} · ${run.acceptance.full_pushup}`;
    }
    if (run.contact) contactGate.textContent = [
      run.contact.profile, `Full push-up: ${run.acceptance.full_pushup}`,
      `Muscle-driven: ${run.acceptance.muscle_driven}`, `External control: ${run.acceptance.external_control}`,
      "Skin pressure: NOT_MODELED",
      ...(run.excluded_display_surfaces?.length ?
        [`Illustrative surfaces excluded after floor-crossing checks: ${run.excluded_display_surfaces.map(row => row.name).join(", ")}`] : []),
    ].join(" · ");
    layerPanel.hidden = false;
    showLayers();
    seek(chosen ? run.frames.findIndex(f => f.state_index === chosen.state_index) : 0);
  }

  el("whole-play").addEventListener("click", () => {
    if (pending) return seek(index);
    if (index === run.frames.length - 1) seek(0);
    started = undefined;
    offset = clock;
    el("whole-play").textContent = "Pause";
    pending = requestAnimationFrame(animate);
  });
  el("whole-restart").addEventListener("click", () => seek(0));
  el("whole-speed").addEventListener("change", () => {
    offset = clock;
    started = undefined;
  });
  timeline.addEventListener("input", () => seek(Number(timeline.value)));
  el("whole-camera").addEventListener("change", event => {
    cameraName = event.target.value;
    setCamera(run.cameras[cameraName]);
  });

  return {
    open, dispose, seek, currentView, setCamera, active: () => !!rig, reset: () => setCamera(run.cameras[cameraName]),
    status: () => run && { frame: run.frames[index], duration: clip.duration, clock, playing: !!pending,
      layers: [...layers], nodeCount: nodes.size },
    sample: (node, vertices) => {
      const object = nodes.get(node);
      return vertices.map(i => object.getVertexPosition(i, scratch).applyMatrix4(object.matrixWorld).toArray());
    },
    matrix: node => nodes.get(node).matrixWorld.toArray(),
    weights: node => nodes.get(node).geometry.attributes.skinWeight?.count,
    surfaceAudit: () => {
      const result = {};
      let floor = 0;
      rig.traverse(o => {
        if (o.name.replaceAll("_", " ") === "World floor" && o.isMesh) {
          floor = o.getVertexPosition(0, scratch).applyMatrix4(o.matrixWorld).y;
        }
      });
      rig.traverse(o => {
        if (!o.isMesh || !["SKELETON", "MUSCLES"].includes(o.userData.layer ?? o.parent.userData.layer)) return;
        const geom = o.geometry;
        const distances = new Float64Array(geom.attributes.position.count);
        let min = Infinity;
        for (let i = 0; i < distances.length; i++) {
          distances[i] = o.getVertexPosition(i, scratch).applyMatrix4(o.matrixWorld).y - floor;
          min = Math.min(min, distances[i]);
        }
        let crossing = 0, below = 0, overTarget = 0;
        for (let i = 0; i < (geom.index?.count ?? distances.length); i += 3) {
          const a = distances[geom.index ? geom.index.getX(i) : i];
          const b = distances[geom.index ? geom.index.getX(i + 1) : i + 1];
          const c = distances[geom.index ? geom.index.getX(i + 2) : i + 2];
          const lo = Math.min(a, b, c), hi = Math.max(a, b, c);
          if (lo < 0 && hi > 0) crossing++;
          if (hi < 0) below++;
          if (lo < -.002) overTarget++;
        }
        result[o.name] = { min, crossing, below, overTarget };
      });
      return { floor, surfaces: result };
    },
  };
}
