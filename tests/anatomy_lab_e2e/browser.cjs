/** Real browser using only the running local site and browser UI for the composite workflow. */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

const [origin, output, legacyOrigin, motionPath] = process.argv.slice(2);
const entries = [["FMA7088", "heart"], ["FMA7309", "right lung"], ["FMA7310", "left lung"], ["FMA50801", "brain"]];
const viewports = { desktop: { width: 1280, height: 900 }, mobile: { width: 390, height: 844 } };
const viewportOptions = (mode) => ({ viewport: viewports[mode], isMobile: mode === "mobile", hasTouch: mode === "mobile" });
const write = (directory, name, obj) => fs.writeFile(path.join(directory, name), JSON.stringify(obj, null, 2) + "\n");
const sha = (x) => crypto.createHash("sha256").update(x).digest("hex");
const areSortedEqual = (a, b) => assert.deepEqual([...a].sort(), [...b].sort());

async function ready(page, url) {
  const start = Date.now();
  await page.goto(url);
  await page.waitForFunction(() => window.hmmViewer?.stats().revision > 0, null, { timeout: 30000 });
  return Date.now() - start;
}

async function paint(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function metrics(page, after = 0) {
  const resources = await page.evaluate(after => performance.getEntriesByType("resource")
    .filter(r => r.startTime >= after).map(r => ({ url: r.name, ms: r.duration, bodyBytes: r.encodedBodySize,
      transferBytes: r.transferSize })), after);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const { metrics } = await cdp.send("Performance.getMetrics");
  await cdp.detach();
  return { resources, jsHeapBytes: metrics.find(item => item.name === "JSHeapUsedSize")?.value,
    glbBodyBytes: resources.filter(r => /\/api\/pack\/|\.glb$/.test(r.url)).reduce((n, r) => n + r.bodyBytes, 0),
    transferBytes: resources.reduce((n, r) => n + r.transferBytes, 0) };
}

function events(page) {
  const records = [];
  page.on("console", m => records.push({ type: "console", level: m.type(), text: m.text() }));
  page.on("pageerror", e => records.push({ type: "pageerror", text: e.message }));
  page.on("request", r => records.push({ type: "request", method: r.method(), url: r.url() }));
  page.on("response", r => records.push({ type: "response", status: r.status(), url: r.url() }));
  page.on("requestfailed", r => records.push({ type: "requestfailed", url: r.url(), error: r.failure() }));
  return records;
}

async function saveScene(page, target) {
  const download = page.waitForEvent("download");
  await page.locator("#export").click();
  await (await download).saveAs(target);
  return JSON.parse(await fs.readFile(target));
}

async function capture(page, target) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await paint(page);
  await page.screenshot({ path: target });
}

async function organ(browser, mode, fma, query) {
  const key = `${fma}-${mode}`;
  const started_at = new Date().toISOString();
  const context = await browser.newContext(viewportOptions(mode));
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const records = events(page);
  try {
    const firstFrameMs = await ready(page, origin);
    const entry = await page.evaluate(() => window.hmmViewer.getScene().scene);
    const initial = await metrics(page);
    assert.ok(entry === "whole-anterior" ? initial.glbBodyBytes > 0 : initial.glbBodyBytes === 0);
    const renderer = await page.evaluate(() => {
      const gl = document.querySelector("#view").getContext("webgl2");
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      return gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
    });
    await page.locator("#query").fill(query);
    const match = page.locator(`#matches [data-fma="${fma}"]`);
    await match.waitFor();
    const searchText = await match.innerText();
    assert.match(searchText, /recorded FJ/);
    const mark = await page.evaluate(() => performance.now());
    const start = Date.now();
    await match.click();
    await page.waitForFunction(fma => window.hmmViewer.getScene().selection[0] === fma, fma);
    await paint(page);
    const selectionVisibleMs = Date.now() - start;
    const selection = await metrics(page, mark);
    const initialNative = await page.evaluate(() => window.hmmViewer.getScene());
    const coverageText = await page.locator("#coverage").textContent();
    assert.match(coverageText, /^(AVAILABLE|PARTIAL) · [1-9]/);
    assert.equal(initialNative.selection[0], fma);
    assert.ok(initialNative.opaque_focus_parts.length > 1);
    assert.ok(initialNative.visible_parts.length > initialNative.opaque_focus_parts.length);
    areSortedEqual(initialNative.visible_parts, await page.evaluate(() => window.hmmViewer.visibleFjIds()));
    await page.locator("#query").fill("");
    await page.locator("#focus").click();
    await capture(page, path.join(output, "visual", `${key}-context.png`));
    await page.locator("#isolate").click();
    await page.getByRole("button", { name: "Restore context" }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.hmmViewer.getScene().visible_parts), initialNative.opaque_focus_parts);
    areSortedEqual(initialNative.opaque_focus_parts, await page.evaluate(() => window.hmmViewer.visibleFjIds()));
    await capture(page, path.join(output, "visual", `${key}-isolated.png`));
    await page.locator("#isolate").click();
    await page.getByRole("button", { name: "Isolate", exact: true }).waitFor();
    areSortedEqual(initialNative.visible_parts, await page.evaluate(() => window.hmmViewer.visibleFjIds()));
    const inspected = initialNative.opaque_focus_parts[0];
    await page.locator("#constituent").selectOption(inspected);
    assert.match(await page.locator("#constituent-info").innerText(), new RegExp(inspected));
    const target = path.join(output, "scenes", `${key}.json`);
    const core = await saveScene(page, target);
    assert.equal(core.schema_version, "hmm.anatomy.scene/1");
    assert.equal(core.composite_view.inspected_fj, inspected);
    assert.equal(core.composite_view.isolated, false);
    await page.reload();
    await page.waitForFunction(entry => window.hmmViewer?.getScene().scene === entry, entry);
    await page.locator("#import").setInputFiles(target);
    await page.waitForFunction(fma => window.hmmViewer.getScene().selection[0] === fma, fma);
    await paint(page);
    assert.equal(await page.locator("#constituent").inputValue(), inspected);
    const imported = await page.evaluate(() => window.hmmViewer.getScene());
    assert.deepEqual(initialNative.opaque_focus_parts, imported.opaque_focus_parts);
    areSortedEqual(initialNative.visible_parts, await page.evaluate(() => window.hmmViewer.visibleFjIds()));
    const reimport = await saveScene(page, path.join(output, "scenes", `${key}-reimported.json`));
    assert.deepEqual(core, reimport);
    if (mode === "desktop") await capture(page, path.join(output, "visual", `${key}-reimported.png`));

    const external = records.filter(e => e.type === "request" && !e.url.startsWith(origin + "/"));
    assert.equal(external.length, 0);
    assert.equal(records.filter(e => e.type === "pageerror" || e.type === "requestfailed").length, 0);
    const result = { status: "PASS", started_at, ended_at: new Date().toISOString(), viewport: viewports[mode], renderer,
      fma, searchText, coverageText, firstFrameMs, initial, selectionVisibleMs, selection,
      selectedFjIds: imported.opaque_focus_parts, contextFjIds: core.composite_view.context_fj_ids,
      exactSceneReimport: true, externalRequests: external, inspected, selectionSHA256: core.composite.selection_sha256,
      visual: [`visual/${key}-context.png`, `visual/${key}-isolated.png`] };
    await write(path.join(output, "logs"), `${key}-browser.json`, { ...result, events: records });
    console.log(`${key}: ${result.selectionVisibleMs} ms, ${selection.glbBodyBytes} GLB bytes, SceneState round-trip equal`);
    return { result, native: imported };
  } catch (error) {
    await capture(page, path.join(output, "visual", `${key}-failure.png`)).catch(() => {});
    await write(path.join(output, "logs"), `${key}-browser.json`, { status: "FAIL", error: String(error), events: records });
    throw error;
  } finally {
    await context.close();
  }
}

async function legacy(browser, mode, fma, native) {
  const context = await browser.newContext(viewportOptions(mode));
  try {
    const page = await context.newPage();
    const firstFrameMs = await ready(page, legacyOrigin);
    const initial = await metrics(page);
    const mark = await page.evaluate(() => performance.now());
    const start = Date.now();
    await page.evaluate(scene => window.hmmViewer.setScene(scene), native);
    await paint(page);
    await page.waitForFunction(() => window.hmmViewer.getScene().scene === "composite");
    const selectionVisibleMs = Date.now() - start;
    const selection = await metrics(page, mark);
    if (mode === "desktop") await capture(page, path.join(output, "visual", `${fma}-desktop-baseline-context.png`));
    return { firstFrameMs, selectionVisibleMs, initial, selection };
  } finally {
    await context.close();
  }
}

async function negatives(browser) {
  const page = await browser.newPage(viewportOptions("desktop"));
  const records = events(page);
  try {
    await ready(page, origin);
    const entry = await page.evaluate(() => window.hmmViewer.getScene().scene);
    await page.route("**/api/query", async route => {
      const method = route.request().postDataJSON();
      if (method.operation !== "anatomy.search") return route.continue();
      const response = await route.fetch();
      const payload = await response.json();
      if (payload.concept) payload.concept.label = "<b>literal source label</b>";
      await route.fulfill({ response, json: payload });
    });
    await page.locator("#query").fill("FMA7088");
    const candidate = page.locator("#matches [data-fma=FMA7088]");
    await candidate.waitFor();
    assert.match(await candidate.innerText(), /<b>literal source label<\/b>/);
    assert.equal(await candidate.locator("b").count(), 0);
    await page.unroute("**/api/query");
    await page.locator("#query").fill("FMA999999999");
    await page.waitForFunction(() => document.querySelector("#search-status").textContent.includes("absent"));
    await page.locator("#import").setInputFiles({ name: "wrong.json", mimeType: "application/json",
      buffer: Buffer.from('{"schema_version":"hmm.anatomy.scene/2"}') });
    await page.waitForFunction(() => document.querySelector("#message").textContent.includes("Invalid scene"));
    await page.locator("#query").fill("FMA7088");
    await candidate.waitFor();
    const cancel = packet => packet.abort();
    await page.route("**/api/pack/**", cancel);
    await candidate.click();
    await page.waitForFunction(() => document.querySelector("#message").textContent.includes("failed to load"));
    assert.equal(await page.evaluate(() => window.hmmViewer.getScene().scene), entry);
    await page.unroute("**/api/pack/**", cancel);
    await candidate.click();
    await page.waitForFunction(() => window.hmmViewer.getScene().selection[0] === "FMA7088");
    await write(path.join(output, "logs"), "browser-negatives.json",
      { status: "PASS", cases: ["literal label", "wrong FMA", "wrong scene schema", "asset interruption and retry"], events: records });
  } finally {
    await page.close();
  }
}

async function motion(browser) {
  if (!motionPath) return;
  const page = await browser.newPage(viewportOptions("desktop"));
  try {
    await ready(page, origin);
    const original = JSON.parse(await fs.readFile(motionPath));
    const api = (operation, fields) => page.evaluate(async ({ operation, fields }) => {
      const response = await fetch("/api/query", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation, ...fields }) });
      return response.json();
    }, { operation, fields });
    const opened = await api("motion.open_saved_run", { run_id: original.run_id });
    assert.equal(opened.status, "ok", JSON.stringify(opened));
    assert.equal(opened.motion_sha256, sha(await fs.readFile(motionPath)));
    await page.locator("#motion").setInputFiles(motionPath);
    await page.locator("#motion-controls").waitFor();
    const frames = [];
    for (const [i, wanted] of original.frames.entries()) {
      await page.locator("#frame").selectOption(String(i));
      await paint(page);
      const frame = await page.evaluate(() => ({ motion: window.hmmViewer.getScene().motion, stats: window.hmmViewer.stats() }));
      assert.equal(frame.motion.state_sha256, wanted.state_sha256);
      assert.equal(frame.motion.state_index, wanted.state_index);
      assert.equal(frame.stats.calls, 3);
      const bound = await api("motion.set_frame", { run_id: original.run_id, state_index: wanted.state_index });
      assert.equal(bound.status, "ok", JSON.stringify(bound));
      assert.equal(bound.scene.motion.state_sha256, wanted.state_sha256);
      if (i === original.frames.length - 1) {
        await page.locator("#frame").selectOption("0");
        await page.locator("#import").setInputFiles({ name: "registered-motion.json", mimeType: "application/json",
          buffer: Buffer.from(JSON.stringify(bound.scene)) });
        await page.waitForFunction(hash => window.hmmViewer.getScene().motion?.state_sha256 === hash, wanted.state_sha256);
      }
      frames.push({ ...frame, registrySceneSha256: bound.scene_sha256 });
      await capture(page, path.join(output, "visual", `shoulder-${wanted.phase}.png`));
    }
    await write(path.join(output, "logs"), "shoulder-browser.json", { status: "PASS", frames });
  } finally {
    await page.close();
  }
}

(async () => {
  const netlog = process.env.HMM_CHROMIUM_NETLOG;
  const graphics = process.env.HMM_BROWSER_GPU === "1"
    ? ["--use-gl=angle", "--use-angle=vulkan", "--enable-features=Vulkan", "--disable-vulkan-surface"]
    : ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"];
  const browser = await chromium.launch({ channel: process.env.HMM_BROWSER_CHANNEL || undefined,
    args: [...graphics, "--disable-background-networking", "--no-proxy-server",
      ...(netlog ? [`--log-net-log=${netlog}`] : [])] });
  try {
    for (const folder of ["logs", "scenes", "visual"]) await fs.mkdir(path.join(output, folder), { recursive: true });
    if (process.env.HMM_ONLY_MOTION === "1") {
      await motion(browser);
      return;
    }
    const rows = [];
    for (const [fma, label] of entries) {
      for (const mode of Object.keys(viewports)) {
        const { result, native } = await organ(browser, mode, fma, mode === "mobile" ? fma : label);
        rows.push({ ...result, baseline: legacyOrigin ? await legacy(browser, mode, fma, native) : null });
      }
    }
    await negatives(browser);
    await motion(browser);
    await write(output, "browser-results.json", { status: "PASS", browser: browser.version(), node: process.version,
      playwright: require("playwright/package.json").version, selectionIdsSHA256: rows.map(r => sha(JSON.stringify(r.selectedFjIds))), rows });
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
