import * as THREE from "three";
import { request } from "./lab_bridge.js";
import { registrationPanel } from "./registration_panel.js";

const metrics = {
  activation: "Activation", excitation: "Excitation", force_N: "Transmission force · signed",
  force_magnitude_N: "Transmission force · magnitude", length_m: "Transmission length",
  velocity_m_per_s: "Transmission velocity", power_W: "Transmission power · signed",
  work_J: "Cumulative sampled work · signed",
};
const width = 320, height = 120, pad = 16;

export function musclePanel({ target, root, nodes, run, motionSha, stateIndex, seek, invalidate, showLayers, focus }) {
  const el = id => document.getElementById(id);
  const panel = el("muscle-inspector");
  const chart = el("muscle-chart");
  const metric = el("muscle-metric");
  const path = el("muscle-path");
  const overlay = el("muscle-overlay");
  const isolate = el("muscle-isolate");
  const opacity = el("muscle-opacity");
  const opacityScope = el("muscle-opacity-scope");
  const browse = el("muscle-browser");
  const options = document.createElement("details");
  options.id = "muscle-options";
  const optionsTitle = document.createElement("summary");
  optionsTitle.textContent = "Surface and time controls";
  options.append(optionsTitle, isolate.closest("label"),
    opacity.closest("label"), opacityScope.closest("label"), el("muscle-window"));
  panel.append(options);
  const registration = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Identity and model route";
  const receiptText = document.createElement("p");
  receiptText.style.overflowWrap = "anywhere";
  const scientific = document.createElement("p");
  scientific.setAttribute("role", "status");
  el("muscle-title").after(scientific, el("muscle-readings"));
  const provenance = document.createElement("p");
  provenance.style.overflowWrap = "anywhere";
  const routes = document.createElement("ul");
  registration.append(summary, routes);
  const sources = document.createElement("details");
  const sourceSummary = document.createElement("summary");
  sourceSummary.textContent = "Saved state and sources";
  sources.append(sourceSummary, el("muscle-identity"), el("muscle-note"), receiptText, provenance);
  const interpretation = document.createElement("details");
  const interpretationSummary = document.createElement("summary");
  interpretationSummary.textContent = "Interpretation and better estimates";
  const estimate = document.createElement("p");
  interpretation.append(interpretationSummary, estimate);
  el("muscle-candidates").after(sources, interpretation, registration);
  const evidence = registrationPanel({after: registration, root, nodes, invalidate});
  const palette = new Map();
  const cache = new Map();
  const ray = new THREE.Raycaster();
  let identity, settings, series, activation, painted = [];
  let generation = 0, publishTimer, exact = true, xAt, yAt, shown = [];
  let searchGeneration = 0, searchOffset = 0, nextOffset = null, shared = false;

  for (const [key, label] of Object.entries(metrics)) metric.add(new Option(label, key));

  function restoreMaterials() {
    for (const [obj, original] of palette) {
      obj.material.dispose();
      obj.material = original;
    }
    painted = [];
    palette.clear();
  }

  function close() {
    generation++;
    clearTimeout(publishTimer);
    restoreMaterials();
    evidence.clear();
    identity = settings = series = activation = undefined;
    cache.clear();
    panel.hidden = true;
    shown = [];
    showLayers();
  }

  function signals(selector, property, window = {}) {
    const key = JSON.stringify([selector, property, window]);
    if (!cache.has(key)) {
      const data = request("muscle.timeseries", {run_id: run().run_id, ...selector, metric: property, ...window});
      if (cache.size >= 16) cache.delete(cache.keys().next().value);
      cache.set(key, data);
      data.catch(() => { if (cache.get(key) === data) cache.delete(key); });
    }
    return cache.get(key);
  }

  function svg(tag, attrs) {
    const child = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs)) child.setAttribute(key, value);
    return child;
  }

  function draw(active) {
    const tracks = active ? [active.values] : series.aggregate ? [series.aggregate] : series.series.map(row => row.values);
    const min = Math.min(...tracks.flat()), max = Math.max(...tracks.flat());
    const lo = series.time_s[0], hi = series.time_s.at(-1);
    xAt = t => pad + (t - lo) / (hi - lo || 1) * (width - 2 * pad);
    yAt = value => height - pad - (value - min) / (max - min || 1) * (height - 2 * pad);
    chart.replaceChildren();
    const bottom = series.phase_anchors.bottom;
    const bottomTime = run().frames[bottom].frame_time;
    if (bottomTime >= lo && bottomTime <= hi) {
      chart.append(svg("line", {x1: xAt(bottomTime), x2: xAt(bottomTime), y1: pad,
        y2: height - pad, stroke: "#a8aab1", "stroke-dasharray": "4 4"}));
    }
    const colors = ["#a9e5cf", "#ffbc79", "#a6c3ff"];
    for (const [i, track] of tracks.entries()) {
      chart.append(svg("polyline", {points: track.map((v, j) => `${xAt(series.time_s[j])},${yAt(v)}`).join(" "),
        fill: "none", stroke: colors[i % colors.length], "stroke-width": 2}));
    }
    chart.append(svg("line", {id: "muscle-cursor", y1: pad, y2: height - pad, stroke: "white"}));
    chart.setAttribute("aria-label", `${metrics[series.metric]} (${series.unit}) by saved time (s)`);
    el("muscle-axes").textContent = `${min.toPrecision(4)} to ${max.toPrecision(4)} ${series.unit} · ${lo.toFixed(2)}–${hi.toFixed(2)} s · ${series.state_indices.length} states`;
    el("muscle-aggregation").textContent = active ? active.exact_name :
      series.aggregation?.replaceAll("_", " ") || "Separate native paths";
  }

  function frame(isExact) {
    exact = isExact;
    if (!settings) return;
    evidence.update(isExact && identity.crosswalk_revision >= 3 ? {
      run_id: run().run_id, motion_sha256: motionSha(), state_index: stateIndex(),
      mapping_revision_sha256: settings.mapping_revision_sha256,
      ...(settings.actuator_id !== null ? {actuator_id: settings.actuator_id} : {display_node: settings.display_node}),
    } : null);
    const actIndex = activation?.state_indices.indexOf(stateIndex());
    if (painted.length && actIndex >= 0) {
      const v = Math.min(1, Math.max(0, activation.aggregate[actIndex]));
      for (const obj of painted) obj.material.color.setRGB(.025 + .955 * v, .15 + .57 * v, .55 - .485 * v);
      el("muscle-legend").textContent = `Uniform model activation · ${v.toPrecision(4)} · 0 blue to 1 gold · linked parts`;
      invalidate();
    }
    const frame = run().frames[stateIndex()];
    receiptText.textContent = [
      `Run ${run().run_id}`, `Motion SHA-256 ${motionSha()}`,
      `Crosswalk v${identity.crosswalk_revision ?? 1} · ${identity.mapping_revision_sha256}`,
      `Saved state #${frame.state_index} · ${frame.frame_time.toFixed(3)} s · SHA-256 ${frame.state_sha256}`,
      isExact ? "Exact saved pose" : "Interpolated render pose · signal held at the saved sample",
      "Attachment footprint: NOT_VERIFIED · Deformation validation: NOT_VERIFIED",
    ].join(" · ");
    if (!series) return;
    const i = series.state_indices.indexOf(frame.state_index);
    const cursor = el("muscle-cursor");
    if (i < 0) {
      cursor.setAttribute("visibility", "hidden");
      el("muscle-value").textContent = `#${frame.state_index} · outside chart samples`;
      return;
    }
    cursor.removeAttribute("visibility");
    cursor.setAttribute("x1", xAt(series.time_s[i]));
    cursor.setAttribute("x2", xAt(series.time_s[i]));
    const active = series.series.find(row => row.actuator_id === settings.actuator_id);
    const raw = (active ? [active] : series.series).map(row =>
      `${row.exact_name} ${row.values[i].toPrecision(6)} ${series.unit}`);
    const aggregate = !active && series.aggregate ? ` · derived ${series.aggregate[i].toPrecision(6)} ${series.unit}` : "";
    el("muscle-value").textContent = `#${frame.state_index} · ${frame.frame_time.toFixed(2)} s · ${series.phases[i]} · ${isExact ? "exact pose" : "sample held during interpolated pose"}${aggregate}\n${raw.join(" · ")}`;
  }

  function publish() {
    clearTimeout(publishTimer);
    if (!settings || !exact || !shared) return;
    const token = generation;
    publishTimer = setTimeout(async () => {
      if (token !== generation) return;
      try {
        await request("muscle.select", {run_id: run().run_id, motion_sha256: motionSha(), state_index: stateIndex(),
          selection: settings, publish: true});
      } catch (error) {
        if (token === generation) displayError(error);
      }
    }, 120);
  }

  async function refresh(publishAfter = true) {
    const token = ++generation;
    evidence.clear();
    routes.replaceChildren();
    receiptText.textContent = "";
    provenance.textContent = "";
    scientific.textContent = "";
    estimate.textContent = "";
    restoreMaterials();
    series = activation = undefined;
    chart.replaceChildren();
    el("muscle-axes").textContent = "";
    el("muscle-aggregation").textContent = "";
    el("muscle-value").textContent = "Loading saved samples…";
    el("muscle-legend").textContent = "";
    invalidate();
    const group = identity.group;
    const chosen = settings;
    const selector = chosen.actuator_id !== null ? {actuator_ids: [chosen.actuator_id]} :
      group ? {group_id: group.group_id} : null;
    el("muscle-readings").hidden = !selector;
    el("muscle-window").hidden = !selector;
    path.disabled = chosen.display_node === null;
    overlay.disabled = chosen.actuator_id !== null || !group;
    el("muscle-legend").hidden = !chosen.overlay;
    const from = el("muscle-from"), to = el("muscle-to");
    const start = run().frames[0].frame_time, end = run().frames.at(-1).frame_time;
    const value = (input, endpoint) => Number(input.value) === Number(endpoint.toFixed(6)) ? endpoint : Number(input.value);
    const window = {start_s: value(from, start), end_s: value(to, end), stride: Number(el("muscle-stride").value)};
    const [receipt, info, values, mapping] = await Promise.all([
      request("muscle.select", {run_id: run().run_id, motion_sha256: motionSha(),
        state_index: stateIndex(), selection: chosen}),
      selector && signals(selector, chosen.metric, window),
      chosen.overlay && signals({group_id: group.group_id}, "activation"),
      identity.crosswalk_revision >= 3 && request("muscle.registration", {
        run_id: run().run_id, motion_sha256: motionSha(), state_index: stateIndex(),
        mapping_revision_sha256: chosen.mapping_revision_sha256,
        ...(chosen.actuator_id !== null ? {actuator_id: chosen.actuator_id} : {display_node: chosen.display_node}),
      }),
    ]);
    if (token !== generation) return;
    const meta = receipt.scientific_quantity;
    const definition = meta.quantities[chosen.metric];
    scientific.textContent = receipt.data_status === "NO_DATA"
      ? "NO_DATA · This display surface has no accepted actuator association."
      : `MODEL OUTPUT · ${metrics[chosen.metric]} (${definition.unit})`;
    estimate.textContent = [
      receipt.data_status === "AVAILABLE" && definition.definition,
      meta.quantities.display_surface?.definition,
      receipt.data_status === "AVAILABLE" && definition.improve_estimate,
      meta.quantities.display_surface?.improve_estimate,
      `Human experimental validation: ${meta.human_validation}. Uncertainty interval: ${meta.uncertainty_interval.status}.`,
    ].filter(Boolean).join(" ");
    provenance.textContent = [
      `Model ${meta.model.id} · revision ${meta.model.revision} · SHA-256 ${meta.model.asset_sha256}`,
      `Run manifest SHA-256 ${meta.source_manifest_sha256}`,
      `${Object.keys(meta.sources_sha256).length} source file hashes in the receipt`,
      `Fixed support equalities: ${meta.controls.fixed_support_equalities}`,
      `Independent comparison: ${meta.reference_comparison.execution_status}`,
      `Contact boundary: ${meta.controls.support_boundary}`,
    ].join(" · ");
    routes.replaceChildren(...(mapping?.rows ?? identity.rows).map(row => {
      const item = document.createElement("li");
      const review = row.registration_review;
      const concepts = row.concept_membership.map(c => `${c.fma_id} ${c.label} [${c.status}]`);
      const route = row.links.map(link => link.name ? `${link.name} (${link.body})` : link.kind);
      item.textContent = [`${row.exact_name} · tendon #${row.tendon_id} · ${row.side}`,
        review?.family && `${review.family} [${review.family_evidence}]`, ...concepts,
        route.join(" → "), ...row.reason_codes ?? []].filter(Boolean).join(" · ");
      return item;
    }));
    shown = receipt.display_nodes;
    el("muscle-focus").disabled = isolate.disabled = opacity.disabled = !shown.length;
    opacityScope.disabled = !identity.asset;
    showLayers();
    activation = values || undefined;
    const shaded = new Set(receipt.overlay?.display_nodes ?? []);
    const translucent = new Set(chosen.opacity < 1 ? receipt.opacity_nodes : []);
    for (const i of new Set([...shaded, ...translucent])) {
      const obj = nodes.get(i);
      if (!obj?.isMesh || Array.isArray(obj.material)) continue;
      palette.set(obj, obj.material);
      obj.material = obj.material.clone();
      if (translucent.has(i)) {
        obj.material.opacity *= chosen.opacity;
        obj.material.transparent = true;
      }
      if (shaded.has(i)) painted.push(obj);
    }
    if (info?.time_s.length) {
      series = info;
      draw(info.series.find(row => row.actuator_id === chosen.actuator_id));
    } else {
      el("muscle-value").textContent = selector ? "No saved sample in this time window." : "";
    }
    frame(exact);
    if (publishAfter) publish();
  }

  async function inspect(node, saved = null, publishAfter = true, native = null) {
    clearTimeout(publishTimer);
    const token = ++generation;
    evidence.clear();
    routes.replaceChildren();
    receiptText.textContent = "";
    const id = saved?.actuator_id ?? native;
    const info = await (node == null
      ? request("muscle.describe", {run_id: run().run_id, query: String(id)})
      : request("muscle.describe", {run_id: run().run_id, display_node: node}));
    if (token !== generation || !info.asset && !info.rows.length) return;
    identity = info;
    const a = info.asset, row = info.rows.find(r => r.id === id);
    settings = saved ?? {mapping_revision_sha256: info.mapping_revision_sha256, display_node: node,
      metric: "activation", actuator_id: id, overlay: false, isolate: false, opacity: 1};
    panel.hidden = false;
    const reviewed = row?.concept_membership.find(c => c.status === "REVIEWED_ANATOMICAL");
    el("muscle-title").textContent = a?.name ?? (reviewed ? `${reviewed.label} · ${row.exact_name}` : row.exact_name);
    el("muscle-identity").textContent = [a?.side || row?.side || "side unreviewed", a?.fma_id ?? reviewed?.fma_id,
      a?.mesh_id, a?.dataset, a?.dataset_revision, info.mapping_status, a?.deformation, a?.registration,
      row?.region].filter(Boolean).join(" · ");
    el("muscle-note").textContent = [info.control, `full_pushup=${info.acceptance.full_pushup}`, `muscle_driven=${info.acceptance.muscle_driven}`,
      `external_control=${info.acceptance.external_control}`, `human_validation=${info.human_validation}`,
      "Model activation is distinct from surface EMG.", !a ? (row.usable.color ? "Illustrative linked display." :
        "Native signal. No approved surface overlay.") : !info.group ? "No accepted native path association." :
      a.part_actuator_id == null ? "Sided group association." : "Display attachment validation is pending."].join(" · ");
    path.replaceChildren(new Option("Sided model paths", ""), ...info.rows.map(r => new Option(r.exact_name, r.id)));
    metric.value = settings.metric;
    path.value = settings.actuator_id ?? "";
    overlay.checked = settings.overlay;
    isolate.checked = settings.isolate ?? false;
    opacity.value = settings.opacity ?? 1;
    opacityScope.value = settings.opacity_scope ?? "selection";
    el("muscle-from").value = Number(run().frames[0].frame_time.toFixed(6));
    el("muscle-to").value = Number(run().frames.at(-1).frame_time.toFixed(6));
    el("muscle-stride").value = "1";
    el("muscle-candidates").replaceChildren(...(info.candidate_actuator_ids ?? []).map(i => {
      const button = document.createElement("button");
      button.textContent = `Review candidate #${i}`;
      button.addEventListener("click", () => inspect(null, null, true, i).catch(displayError));
      return button;
    }));
    await refresh(publishAfter);
  }

  function displayError(error) { el("message").textContent = error.message; }
  function change() {
    settings = {...settings, metric: metric.value, actuator_id: path.value === "" ? null : Number(path.value),
      overlay: overlay.checked && path.value === "", isolate: isolate.checked, opacity: Number(opacity.value),
      opacity_scope: opacityScope.value};
    overlay.checked = settings.overlay;
    refresh().catch(displayError);
  }

  function hit(clientX, clientY, camera, diagnostic = false) {
    const bounds = target.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((clientX - bounds.left) / bounds.width * 2 - 1,
      -(clientY - bounds.top) / bounds.height * 2 + 1), camera);
    const visible = [];
    root().traverseVisible(obj => {
      if (obj.isMesh) {
        // Skin bounds are pose dependent, and this runs only on an intentional pick.
        if (obj.isSkinnedMesh) obj.boundingSphere = null;
        visible.push(obj);
      }
    });
    const first = ray.intersectObjects(visible, false)[0]?.object;
    if (!first) return null;
    const found = [...nodes.entries()].find(([, obj]) => obj === first || obj === first.parent)?.[0] ?? null;
    if (diagnostic) return {node: found, name: first.name, layer: first.userData.layer};
    return (first.userData.layer ?? first.parent?.userData.layer) === "MUSCLES" ? found : null;
  }

  metric.addEventListener("change", change);
  path.addEventListener("change", change);
  overlay.addEventListener("change", change);
  isolate.addEventListener("change", change);
  opacity.addEventListener("change", change);
  opacityScope.addEventListener("change", change);
  el("muscle-focus").addEventListener("click", () => focus(shown));
  el("muscle-window").addEventListener("submit", event => {
    event.preventDefault();
    refresh(false).catch(displayError);
  });
  chart.addEventListener("click", event => {
    if (!series) return;
    const rect = chart.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * width;
    let best = 0;
    for (let i = 1; i < series.time_s.length; i++) {
      if (Math.abs(xAt(series.time_s[i]) - x) < Math.abs(xAt(series.time_s[best]) - x)) best = i;
    }
    seek(series.state_indices[best]);
  });
  el("muscle-close").addEventListener("click", close);
  el("muscle-sync").addEventListener("click", async () => {
    el("muscle-sync").disabled = true;
    try {
      const value = await request("muscle.selection", {run_id: run().run_id});
      if (!value.selection) throw new Error("No shared exact muscle selection");
      seek(value.frame.state_index);
      await inspect(value.selection.display_node, value.selection, false);
    } catch (error) { displayError(error); }
    finally { el("muscle-sync").disabled = false; }
  });

  async function list(offset = 0) {
    const token = ++searchGeneration;
    const filter = el("muscle-filter").value;
    const inventory = filter === "geometry_only" ? "display" : el("muscle-inventory").value;
    const data = await request("muscle.search", {run_id: run().run_id, inventory, brief: true, offset,
      query: el("muscle-query").value, side: el("muscle-side").value || null,
      region: el("muscle-region").value || null, status: filter || null});
    if (token !== searchGeneration || browse.hidden) return;
    searchOffset = offset;
    nextOffset = data.next_offset;
    const items = inventory === "native" ? data.rows : data.assets;
    el("muscle-results").replaceChildren(...items.map(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.actuator = item.id ?? "";
      button.dataset.node = item.display_copy ?? "";
      const label = inventory === "native" ? [item.reviewed_labels[0], item.exact_name, `#${item.id}`, item.status] :
        [item.name, item.mesh_id, item.selection_status];
      button.textContent = label.filter(Boolean).join(" · ");
      button.addEventListener("click", () => {
        seek(stateIndex());
        inspect(item.display_copy ?? null, null, true, item.id ?? null).catch(displayError);
      });
      return button;
    }));
    el("muscle-list-count").textContent = data.count ? `${offset + 1}–${offset + items.length} of ${data.count}` : "No matches";
    el("muscle-prev").disabled = !offset;
    el("muscle-next").disabled = nextOffset === null;
  }
  el("muscle-search").addEventListener("submit", event => {event.preventDefault(); list().catch(displayError);});
  el("muscle-prev").addEventListener("click", () => list(Math.max(0, searchOffset - 20)).catch(displayError));
  el("muscle-next").addEventListener("click", () => list(nextOffset).catch(displayError));
  browse.addEventListener("toggle", () => { if (browse.open && !browse.hidden) list().catch(displayError); });

  return {close, frame, publish, hit, inspect, settings: () => settings, shown: () => shown,
    open: analytics => {
      ++searchGeneration;
      browse.hidden = !analytics;
      browse.open = false;
      el("muscle-results").replaceChildren();
      shared = !!analytics?.shared_selection;
      el("muscle-sync").hidden = !shared;
    }};
}
