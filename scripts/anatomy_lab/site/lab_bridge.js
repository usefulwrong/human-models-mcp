/** Apply a typed Anatomy Lab scene through the local registry. */
export async function request(operation, fields, path = "/api/query") {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation, ...fields }),
    });
  } catch {
    throw new Error("The local Anatomy Lab server is unavailable");
  }
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error(`The local Anatomy Lab server returned HTTP ${response.status}`);
  }
  const result = await response.json();
  if (result.status !== "ok") throw new Error(result.error?.message || "Anatomy Lab request failed");
  return result;
}

export async function resolveComposite(concept, representation) {
  const fields = { concept, representation, limit: 200 };
  const first = await request("anatomy.resolve", fields);
  const members = [...first.members];
  const packs = { ...first.packs };
  let offset = first.next_offset;
  while (offset !== null) {
    if (offset !== members.length || offset >= first.counts.members || offset > 10000) {
      throw new Error("Invalid composite membership page");
    }
    const page = await request("anatomy.resolve", { ...fields, offset });
    if (first.selection_sha256 !== page.selection_sha256 || !page.members.length) {
      throw new Error("Composite membership changed during loading");
    }
    members.push(...page.members);
    Object.assign(packs, page.packs);
    offset = page.next_offset;
  }
  if (first.schema_version !== "hmm.anatomy.composite/1" || members.length !== first.counts.members ||
      members.some((member, index) => index && members[index - 1].fj_id >= member.fj_id) ||
      members.filter(member => member.renderable).length !== first.counts.renderable ||
      Object.keys(packs).length !== first.pack_count) {
    throw new Error("Incomplete composite membership");
  }
  return { ...first, members, packs };
}

export async function applyCoreScene(scene, viewer) {
  const exported = await request("scene.export", { scene });
  const state = exported.scene;
  if (state.motion) {
    const { motion } = await request("scene.export", { scene: state }, "/api/motion");
    viewer.installMotion(motion);
    viewer.showFrame(motion.frames.findIndex(frame => frame.state_index === state.motion.state_index));
  } else if (state.composite) {
    const resolution = await resolveComposite(state.selection[0], state.composite.representation);
    await viewer.setComposite(state, resolution);
  } else {
    const { camera, selection, visible_layers } = state;
    const native = viewer.getScene();
    if (camera.frame !== "packed_atlas_m" || camera.fov_axis !== "vertical" ||
        camera.view_asset_sha256 !== native.source_sha256) {
      throw new Error("Scene camera belongs to a different viewer asset or coordinate frame");
    }
    const semanticLayers = {
      bones: ["bone", "cartilage"], muscles: ["muscle"], organs: ["organ", "digestive", "respiratory",
        "urinary", "endocrine", "reproductive"], vasculature: ["artery", "vein", "lymphatic"],
      other: ["nervous", "skin", "connective", "other", "tissue"],
    };
    await viewer.setScene({ ...native, motion: undefined, selection,
      visible_layers: visible_layers.flatMap(layer => semanticLayers[layer]),
      camera: { frame: "packed-atlas-m", position: camera.position, target: camera.target,
        up: camera.up, fov_degrees: camera.fov_degrees },
    });
  }
  return exported.scene_sha256;
}
