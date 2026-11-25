/** Run only with a disposable copy of the generated site. */
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { copyFile, rename, stat, writeFile, readFile } = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

const [python, sourceSite, site, sceneFile, evidenceFile] = process.argv.slice(2);
const origin = "http://127.0.0.1:18944";
const planDirectory = "full/site/packs";
const cached = path.join(site, planDirectory);
const good = path.join(sourceSite, planDirectory);
const rep = { dataset: "BodyParts3D", mesh_version: "4.3", membership_version: "4.3+4.3i" };
const delay = () => new Promise(resolve => setTimeout(resolve, 100));

async function query(value) {
  const response = await fetch(origin + "/api/query", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
  assert.ok(response.ok);
  return response.json();
}

(async () => {
  assert.notEqual(path.resolve(sourceSite), path.resolve(site));
  const processOut = spawn(python, ["-m", "lab_web", "--site", site, "--port", "18944"], { stdio: "inherit" });
  const closed = once(processOut, "exit");
  const browser = await chromium.launch({ channel: "chrome", args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
  const page = await browser.newPage();
  const requests = [];
  page.on("requestfailed", r => requests.push({ url: r.url(), error: r.failure() }));
  page.on("response", r => requests.push({ url: r.url(), status: r.status() }));
  page.on("console", m => requests.push({ console: m.text(), level: m.type() }));
  try {
    for (let i = 0; i < 100; i++) {
      if (await fetch(origin).then(r => r.ok, () => false)) break;
      assert.equal(processOut.exitCode, null);
      await delay();
    }
    const request = { operation: "anatomy.resolve", representation: rep, concept: "FMA7088", limit: 200 };
    const original = await query(request);
    const [missing, corrupt] = Object.keys(original.packs);
    assert.ok(missing && corrupt && missing !== corrupt);
    const cachedCorrupt = path.join(cached, corrupt);
    const corruptFile = cachedCorrupt + ".fault";
    await rename(path.join(cached, missing), path.join(cached, missing + ".missing"));
    await writeFile(corruptFile, Buffer.alloc((await stat(cachedCorrupt)).size), { flag: "wx" });
    await rename(corruptFile, cachedCorrupt);
    const queryAfter = await query(request);
    const expectedMissing = original.members.filter(m => m.pack === missing).length;
    assert.equal(queryAfter.counts.missing_display, expectedMissing);
    assert.equal(queryAfter.coverage, "PARTIAL");
    assert.equal((await fetch(`${origin}/api/pack/${corrupt}/${original.packs[corrupt].sha256}`)).status, 404);
    assert.equal((await fetch(`${origin}/api/pack/${missing}/${original.packs[missing].sha256}`)).status, 404);
    const goodScene = JSON.parse(await readFile(sceneFile));
    assert.equal((await query({ operation: "scene.export", scene: goodScene })).status, "integrity_error");

    await page.goto(origin);
    await page.waitForFunction(() => window.hmmViewer);
    const entry = await page.evaluate(() => window.hmmViewer.getScene().scene);
    await page.locator("#query").fill("FMA7088");
    const candidate = page.locator("#matches [data-fma=FMA7088]");
    await candidate.click();
    await page.waitForFunction(() => document.querySelector("#message").textContent.includes("failed to load"));
    const assetError = await page.locator("#message").innerText();
    assert.ok(assetError.includes(corrupt));
    assert.equal(await page.evaluate(() => window.hmmViewer.getScene().scene), entry);
    await copyFile(path.join(good, corrupt), corruptFile);
    await rename(corruptFile, cachedCorrupt);
    await candidate.click();
    await page.waitForFunction(() => window.hmmViewer.getScene().selection[0] === "FMA7088");
    const partial = await page.locator("#coverage").textContent();
    assert.match(partial, new RegExp(`${expectedMissing} missing display meshes`));
    const visible = await page.evaluate(() => window.hmmViewer.getScene().opaque_focus_parts);
    assert.equal(visible.length, original.counts.renderable - expectedMissing);
    processOut.kill();
    const exit = await closed;
    await page.locator("#query").fill("brain");
    await page.waitForFunction(() => document.querySelector("#search-status").textContent.includes("server is unavailable"));
    const serverError = await page.locator("#search-status").innerText();
    assert.deepEqual(visible, await page.evaluate(() => window.hmmViewer.getScene().opaque_focus_parts));
    await writeFile(evidenceFile, JSON.stringify({ status: "PASS", missing, corrupt, expectedMissing,
      partial, assetError, serverError, processExit: exit, unchangedVisibleSelection: true, requests }, null, 2) + "\n");
    console.log("PASS: missing/corrupt files, stale scene, recovery and interruption of the owned local process");
  } finally {
    if (processOut.exitCode === null && !processOut.signalCode) processOut.kill();
    await browser.close();
    await closed;
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
