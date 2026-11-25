import { request } from "./lab_bridge.js";

const el = id => document.getElementById(id);
const create = (tag, text) => {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  return node;
};
const cap = text => text ? text[0].toUpperCase() + text.slice(1) : "";
const side = value => ({left: "Patient left", right: "Patient right", midline: "Midline",
  unpaired: "Unpaired", unknown: "Side unspecified"})[value] ?? "Side unspecified";

const systems = [
  ["Skeletal", "FMA23881", "PART-OF", [["Rib cage", "FMA7480"]]],
  ["Muscular", "FMA5022", "IS-A", [["Shoulder muscles", "FMA33531"]]],
  ["Nervous", "FMA7157", "PART-OF", [["Brain", "FMA50801"]]],
  ["Respiratory", "FMA7158", "PART-OF", [["Right lung", "FMA7309"], ["Left lung", "FMA7310"]]],
  ["Circulatory", "FMA7161", "PART-OF", [["Heart", "FMA7088"]]],
  ["Digestive", "FMA7152", "PART-OF", [["Stomach", "FMA7148"], ["Liver", "FMA7197"]]],
  ["Urinary", "FMA7159", "PART-OF", [["Kidney", "FMA7203"]]],
  ["Endocrine", "FMA9668", "PART-OF", []],
  ["Integumentary", "FMA72979", "PART-OF", []],
];
const featured = [["Heart", "FMA7088"], ["Right lung", "FMA7309"], ["Left lung", "FMA7310"], ["Brain", "FMA50801"]];
const rep = () => ({dataset: "BodyParts3D", mesh_version: "4.3", membership_version: el("membership").value});

function button(text, run, detail) {
  const node = create("button", text);
  node.type = "button";
  if (detail) node.append(create("small", detail));
  node.addEventListener("click", run);
  return node;
}

function conceptButton(row, run) {
  const label = cap(row.label) || row.id;
  const count = row.visual_membership_count;
  const note = [side(row.side), row.id, Number.isInteger(count) && (count ? `${count} recorded FJ` : "No recorded meshes")]
    .filter(Boolean).join(" · ");
  const node = button(label, run, note);
  node.dataset.fma = row.id;
  return node;
}

export function installExplorer({ compositeEnabled, chooseComposite, showMesh, metadata }) {
  let searchTimer, searchRevision = 0, treeRevision = 0, meshRevision = 0;
  let searchOpen = true;
  let path = [];
  let currentSystem;
  let inspectedConcept;

  function setConcept(concept, note) {
    inspectedConcept = concept?.id;
    el("preferred-name").textContent = cap(concept?.label) || "Human atlas";
    el("concept-meta").textContent = concept ? `${side(concept.side)} · ${concept.id}` : "BodyParts3D · anterior surface preview";
    el("intro").textContent = note || "";
    el("intro").hidden = !note;
    el("locate").hidden = !concept;
  }

  function renderMatches() {
    const query = el("query").value.trim();
    const token = ++searchRevision;
    clearTimeout(searchTimer);
    el("matches").replaceChildren();
    el("search-status").textContent = "";
    if (!query) return;
    searchOpen = true;
    if (!compositeEnabled) {
      const q = query.toLowerCase();
      for (const part of Object.values(metadata.parts).filter(p =>
        [p.label, p.fma, p.fj].some(s => s.toLowerCase().includes(q))).slice(0, 30)) {
        const row = create("li");
        row.append(button(part.label, () => showMesh(part.fj), part.fj));
        el("matches").append(row);
      }
      return;
    }
    const representation = rep();
    searchTimer = setTimeout(async () => {
      try {
        const result = await request("anatomy.search", {query, representation});
        if (token !== searchRevision || !searchOpen) return;
        const rows = result.concept ? [result.concept] : result.matches;
        for (const row of rows) {
          const item = create("li");
          if (result.namespace === "FJ" || result.namespace === "BP") {
            const part = metadata.parts[row.id];
            const node = button(part?.label ?? row.id, () => showMesh(row.id), `${row.id} · ${side(row.side)}`);
            node.dataset.fj = row.id;
            item.append(node);
          } else item.append(conceptButton(row, () => chooseComposite(row.id, representation)));
          el("matches").append(item);
        }
        el("search-status").textContent = rows.length > 1 ? "Multiple records. Choose a name and patient side." :
          rows.length ? "" : "No matching structure in this catalog.";
      } catch (error) {
        if (token === searchRevision) el("search-status").textContent = error.message;
      }
    }, 180);
  }

  function dismissSearch() {
    searchOpen = false;
    el("matches").replaceChildren();
    el("search-status").textContent = "";
    el("query").value = "";
  }
  el("query").addEventListener("input", renderMatches);
  el("query").addEventListener("keydown", event => {
    if (event.key === "Escape") dismissSearch();
    if (event.key === "Enter") el("matches").querySelector("button")?.focus();
  });

  async function browse(fma, reset = false) {
    if (reset) path = [];
    if (path.at(-1) !== fma) path.push(fma);
    const token = ++treeRevision;
    const representation = rep();
    const predicate = el("hierarchy").value === "IS-A" ? "is_a" : "part_of";
    const spec = {concept: fma, predicate, depth: 1, limit: 18, include_labels: true};
    const relations = el("relations");
    el("tree").hidden = false;
    el("tree-back").disabled = path.length < 2;
    el("branch").textContent = "";
    relations.textContent = "Loading documented relationships…";

    async function edges(direction, offset, list) {
      const result = await request("anatomy.relationships", {...spec, direction, offset});
      if (token !== treeRevision) return;
      if (!result.relationships.length && offset === 0) list.append(create("li", "No direct edges in this source scope."));
      for (const edge of result.relationships) {
        const row = create("li");
        const desc = edge.provenance.version ?? edge.source_id;
        const found = edge.related_concept;
        row.append(button(cap(found.label), () => browse(found.id),
          `${side(found.side)} · ${desc}`));
        list.append(row);
      }
      if (result.next_offset !== null) {
        const item = create("li");
        item.append(button("More relationships", async () => {
          item.remove();
          try { await edges(direction, result.next_offset, list); }
          catch (error) { if (token === treeRevision) list.append(create("li", error.message)); }
        }));
        list.append(item);
      }
    }
    try {
      const {concept, provenance} = await request("anatomy.search", {query: fma, representation});
      if (token !== treeRevision) return;
      el("branch").append(create("strong", cap(concept.label)),
        create("p", `${side(concept.side)} · ${concept.id}`),
        button(concept.visual_membership_count ? "Open this structure" : "Inspect catalog record",
          () => chooseComposite(fma, representation)));
      el("tree-note").textContent = `Source label: ${provenance.version ?? concept.source_id}. ` +
        (predicate === "part_of" ? "Part of gives recorded composition." : "Is a type of gives recorded classification.");
      relations.replaceChildren();
      const lists = ["out", "in"].map(direction => {
        const list = create("ul");
        list.className = "edge-list";
        relations.append(create("h3", direction === "out" ? "Parents" : "Children"), list);
        return edges(direction, 0, list);
      });
      await Promise.all(lists);
    } catch (error) {
      if (token === treeRevision) relations.textContent = `Source coverage unavailable. ${error.message}`;
    }
  }

  if (compositeEnabled) {
    for (const [label, fma] of featured) {
      el("shortcuts").append(button(label, () => chooseComposite(fma, rep())));
    }
    for (const [name, fma, predicate, entries] of systems) {
      const node = button(name, () => {
        currentSystem?.setAttribute("aria-pressed", "false");
        currentSystem = node;
        node.setAttribute("aria-pressed", "true");
        el("hierarchy").value = predicate;
        el("system-examples")?.remove();
        if (entries.length) {
          const examples = create("div");
          examples.id = "system-examples";
          examples.className = "shortcuts";
          examples.setAttribute("aria-label", "Atlas shortcuts");
          for (const [label, id] of entries) examples.append(button(label, () => chooseComposite(id, rep())));
          el("tree").before(examples);
        }
        browse(fma, true);
      });
      node.setAttribute("aria-pressed", "false");
      el("systems").append(node);
    }
    const unknown = button("Other systems", () => {}, "Mapping unreviewed");
    unknown.disabled = true;
    el("systems").append(unknown);
  } else {
    el("systems").textContent = "System hierarchy requires a provisioned composite catalog.";
  }
  el("tree-back").addEventListener("click", () => {
    path.pop();
    browse(path.at(-1));
  });
  el("hierarchy").addEventListener("change", () => { if (path.length) browse(path.at(-1)); });
  el("locate").addEventListener("click", () => {
    if (!inspectedConcept) return;
    currentSystem?.setAttribute("aria-pressed", "false");
    currentSystem = undefined;
    el("system-examples")?.remove();
    browse(inspectedConcept, true);
    el("tree").scrollIntoView({block: "nearest"});
  });
  el("membership").addEventListener("change", () => {
    renderMatches();
    if (path.length) browse(path.at(-1));
  });

  async function identify(id, representation = rep(), concept, offset = 0) {
    const panel = el("mesh-panel");
    const candidates = el("mesh-candidates");
    const info = el("constituent-info");
    const token = ++meshRevision;
    panel.hidden = !id;
    if (!offset) {
      info.textContent = "";
      candidates.replaceChildren();
    }
    if (!id) return;
    const part = metadata.parts[id];
    info.textContent = [id, part && `Catalog label: ${part.label}`, part && side(part.side)]
      .filter(Boolean).join(" · ");
    if (!compositeEnabled) return;
    try {
      const data = await request("anatomy.identify", {mesh: id, representation, offset, limit: 8});
      if (token !== meshRevision) return;
      const {mesh} = data;
      info.textContent += `\n${mesh.identity_status === "DISPUTED" ? "Conflicting FMA claims" : "Source mesh"}` +
        (data.bp_conflict ? ` · BP disagreement (${mesh.bp_id} / ${mesh.obj_representation_id})` : "") +
        `\n${data.candidate_count} candidate concepts · BodyParts3D ${representation.mesh_version}`;
      if (["left", "right"].includes(concept?.side) && ["left", "right"].includes(part?.side) &&
          concept.side !== part.side) {
        info.textContent += `\nLaterality differs: selection is patient ${concept.side}; mesh label is patient ${part.side}.`;
      }
      if (!offset) {
        const details = create("details");
        details.append(create("summary", "Mesh source records"));
        const text = create("p", [
          `Master: ${mesh.master_fma_id ?? "unknown"} · ${mesh.bp_id ?? "unknown"}`,
          `Mirror filename: ${mesh.pinned_filename_fma_id ?? "unknown"}`,
          `OBJ header: ${mesh.obj_concept_id ?? "unknown"} · ${mesh.obj_representation_id ?? "unknown"}`,
          `Source: ${mesh.source_id}`,
          `SHA-256: ${mesh.sha256 ?? "unknown"}`,
        ].join("\n"));
        text.className = "mesh-sources";
        details.append(text);
        candidates.append(details);
        if (data.candidate_count) candidates.append(create("p", "Choose a concept. A mesh can appear in several composites."));
      }
      for (const row of data.candidates) {
        const detail = [side(row.side), row.id, row.identity_claims.length ? "Identity claim" : "Visual membership"];
        if (row.memberships.length) detail.push([...new Set(row.memberships.map(m =>
          m.source_id === "bp3d_43_components" ? "4.3" : "4.3i"))].join(" + "));
        const node = button(cap(row.label) || row.id, () => chooseComposite(row.id, representation), detail.join(" · "));
        node.dataset.fma = row.id;
        candidates.append(node);
      }
      if (data.next_offset !== null) {
        const next = button("More candidate concepts", () => {
          next.remove();
          identify(id, representation, concept, data.next_offset);
        });
        candidates.append(next);
      }
    } catch (error) {
      if (token === meshRevision) info.textContent += `\n${error.message}`;
    }
  }
  return { dismissSearch, identify, setConcept };
}
