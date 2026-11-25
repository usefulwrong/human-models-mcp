import * as THREE from "three";
import { request } from "./lab_bridge.js";

export function wholeMotion({ loader, group, camera, orbit, invalidate, enter }) {
  const el = id => document.getElementById(id);
  const timeline = el("whole-timeline");
  const layerPanel = el("whole-layers");
  const controls = el("whole-controls");
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
    timeline.value = index;
    el("whole-time").textContent = exact ?
      `#${frame.state_index} · ${frame.frame_time.toFixed(2)} s · ${frame.phase}` :
      `${(clock + run.frames[0].frame_time).toFixed(2)} s · interpolated (near #${frame.state_index})`;
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
    if (seconds >= clip.duration) {
      seek(run.frames.length - 1);
      return;
    }
    while (index + 1 < run.frames.length &&
           run.frames[index + 1].frame_time - run.frames[0].frame_time <= seconds) index++;
    pose(seconds);
    readout(false);
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
        });
        const title = { SKELETON: "Skeleton", MUSCLES: "Muscles", ORGANS: "Organs · static atlas",
          SKIN: "Skin · static atlas", OVERLAYS: "Contact pads" }[name];
        label.append(check, " " + title);
        label.title = layer.description;
        return label;
      }));
    cameraName = run.default_camera;
    el("whole-camera").value = cameraName;
    setCamera(chosen?.camera ?? run.cameras[cameraName]);
    controls.hidden = false;
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
    open, dispose, seek, currentView, active: () => !!rig, reset: () => setCamera(run.cameras[cameraName]),
    status: () => run && { frame: run.frames[index], duration: clip.duration, clock, playing: !!pending,
      layers: [...layers], nodeCount: nodes.size },
    sample: (node, vertices) => {
      const object = nodes.get(node);
      return vertices.map(i => object.getVertexPosition(i, scratch).applyMatrix4(object.matrixWorld).toArray());
    },
    matrix: node => nodes.get(node).matrixWorld.toArray(),
    weights: node => nodes.get(node).geometry.attributes.skinWeight?.count,
  };
}
