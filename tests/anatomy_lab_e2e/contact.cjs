/** Inspect the installed MotionScene on desktop and mobile hardware WebGL. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");
const [origin, directory] = process.argv.slice(2);

async function main() {
  await fs.mkdir(directory, {recursive: true});
  const motion = JSON.parse(await fs.readFile("/clip/motion.json"));
  const coverage = JSON.parse(await fs.readFile("/clip/coverage.json"));
  const samples = JSON.parse(await fs.readFile("/clip/samples.json"));
  const glb = await fs.readFile("/clip/motion.glb");
  const nodes = JSON.parse(glb.subarray(20, 20 + glb.readUInt32LE(12))).nodes;
  const proxies = nodes.flatMap((n, i) => n.extras?.layer === "OVERLAYS" && Number.isInteger(n.extras?.geom)
    ? [[i, n.extras.geom]] : []);
  const phases = motion.frames.filter(f => f.phase !== "motion");
  const browser = await chromium.launch({args: ["--use-gl=angle", "--use-angle=vulkan",
    "--enable-features=Vulkan", "--disable-vulkan-surface", "--no-sandbox"]});
  const errors = [], results = {};
  try {
    for (const mobile of [false, true]) {
      const label = mobile ? "mobile" : "desktop";
      const context = await browser.newContext({
        viewport: mobile ? {width: 393, height: 852} : {width: 1440, height: 900},
        isMobile: mobile, hasTouch: mobile,
      });
      const page = await context.newPage();
      page.on("pageerror", error => errors.push(error.message));
      page.on("request", request => assert.ok(request.url().startsWith(origin) || request.url().startsWith("blob:")));
      page.on("requestfailed", request => errors.push(request.url() + " " + request.failure().errorText));
      const start = Date.now();
      await page.goto(origin + "/?motion=whole");
      await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400, null, {timeout: 45000});
      const backend = await page.evaluate(() => {
        const gl = document.querySelector("#view").getContext("webgl2");
        return gl.getParameter(gl.getExtension("WEBGL_debug_renderer_info").UNMASKED_RENDERER_WEBGL);
      });
      assert.match(backend, /NVIDIA.*Vulkan/i);
      const row = results[label] = {renderer: backend, firstFrameMs: Date.now() - start, frames: [], audit: {}};
      const canvas = page.locator("#view");
      const overlay = page.locator('input[value="OVERLAYS"]');
      assert.equal(await overlay.isChecked(), false);
      for (const f of phases) {
        const frame = await page.evaluate(index => {
          window.hmmViewer.whole.seek(index);
          return window.hmmViewer.whole.status().frame;
        }, f.state_index);
        assert.deepEqual(frame, f);
        await page.screenshot({path: `${directory}/${label}-${f.phase.replaceAll(" ", "-")}.png`});
        row.frames.push(frame);
      }
      if (!mobile) {
        let max = 0, proxyMax = 0;
        for (const f of motion.frames) {
          const indexes = coverage.native_bones.map((b, i) => [b.node, samples.points[i].vertices]);
          const [actual, matrices] = await page.evaluate(({index, indexes, proxies}) => {
            const v = window.hmmViewer.whole;
            v.seek(index);
            return [indexes.map(([node, ids]) => v.sample(node, ids)), proxies.map(([node]) => v.matrix(node))];
          }, {index: f.state_index, indexes, proxies});
          for (let i = 0; i < actual.length; i++) for (let j = 0; j < actual[i].length; j++) {
            const p = samples.points[i].world_glb_m[f.state_index][j];
            max = Math.max(max, Math.hypot(...actual[i][j].map((x, k) => x - p[k])));
          }
          const reorder = [0, 2, 1, 3], signs = [1, 1, -1, 1];
          for (let i = 0; i < proxies.length; i++) {
            const native = samples.geom_pose_world_m[proxies[i][1]][f.state_index];
            for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++) {
              const value = native[reorder[row]][reorder[col]] * signs[row] * signs[col];
              proxyMax = Math.max(proxyMax, Math.abs(value - matrices[i][4 * col + row]));
            }
          }
        }
        assert.ok(max <= .0001 && proxyMax <= .0001, {max, proxyMax});
        row.all_saved_native_max_point_error_m = max;
        row.proxy_count = proxies.length;
        row.all_saved_proxy_matrix_max_error = proxyMax;
        const indices = [...new Set([...phases.map(f => f.state_index), 10, 27, 45, 65, 72, 90])];
        for (const i of indices) {
          row.audit[i] = await page.evaluate(index => {
            window.hmmViewer.whole.seek(index);
            return window.hmmViewer.whole.surfaceAudit();
          }, i);
          assert.ok(Math.abs(row.audit[i].floor - (motion.contact?.floor.position_m[2] ?? 0)) < 1e-8);
        }
      }
      await page.evaluate(i => window.hmmViewer.whole.seek(i), phases[1].state_index);
      if (motion.contact) {
        await overlay.check();
        assert.match(await page.locator("#whole-time").textContent(), /loaded contacts.*mm/);
        assert.ok((await page.evaluate(() => window.hmmViewer.whole.status())).layers.includes("OVERLAYS"));
        await canvas.screenshot({path: `${directory}/${label}-debug.png`});
      }
      for (const [part, name] of Object.entries({ "right-hand": "hand_detail_r_thumbdist",
        "left-hand": "hand_detail_l_thumbdist", "right-toe": "r_bofoot", "left-toe": "l_bofoot" })) {
        const bone = coverage.native_bones.find(b => b.name === name);
        for (const [view, offset] of Object.entries(mobile ? {oblique: [.19,.10,.19]} :
          {side: [0,.025,.29], front: [.31,.025,0], oblique: [.19,.10,.19], underside: [.13,-.13,.17]})) {
          await page.evaluate(({node, offset}) => {
            const api = window.hmmViewer.whole;
            const target = api.matrix(node).slice(12, 15);
            api.setCamera({target, position: target.map((value, i) => value + offset[i]), fov: 31});
          }, {node: bone.node, offset});
          await canvas.screenshot({path: `${directory}/${label}-${part}-${view}.png`});
        }
      }
      await context.close();
    }
    assert.deepEqual(errors, []);
    await fs.writeFile(`${directory}/verification.json`, JSON.stringify({run_id: motion.run_id,
      trajectory_sha256: motion.trajectory_sha256, errors, results}, null, 2) + "\n");
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
