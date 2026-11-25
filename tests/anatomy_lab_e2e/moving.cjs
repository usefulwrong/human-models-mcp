/** Whole-body geometry, editable view state and hardware WebGL through the real Explorer. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const [origin, directory, samplesPath] = process.argv.slice(2);
const cubeTolerance = .0001;
const percentile = (values, ratio) => [...values].sort((a, b) => a - b)[Math.round(ratio * (values.length - 1))];
const write = (name, value) => fs.writeFile(`${directory}/${name}.json`, JSON.stringify(value, null, 2) + "\n");

async function run() {
  const samples = JSON.parse(await fs.readFile(samplesPath));
  const coverage = JSON.parse(await fs.readFile(samplesPath.replace(/samples\.json$/, "coverage.json")));
  const geoms = coverage.native_bones.map(b => b.geom_id);
  await fs.mkdir(directory, {recursive: true});
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=vulkan",
    "--enable-features=Vulkan", "--disable-vulkan-surface", "--no-sandbox"] });
  const performance = [], faults = [];
  try {
    for (let repeat = 0; repeat < 3; repeat++) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
      const page = await context.newPage();
      page.on("pageerror", e => faults.push(e.message));
      page.on("requestfailed", r => faults.push(r.url() + " " + r.failure().errorText));
      page.on("request", r => assert.ok(r.url().startsWith(origin) || r.url().startsWith("blob:"), r.url()));
      const start = Date.now();
      await page.goto(origin + "/?motion=whole");
      try {
        await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400, null, {timeout: 25000});
      } catch (error) {
        console.error(await page.locator("#message").textContent(), faults);
        throw error;
      }
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
      const firstFrameMs = Date.now() - start;
      const backend = await page.evaluate(() => {
        const canvas = document.querySelector("#view");
        const gl = canvas.getContext("webgl2");
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        const renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
        window.hmmViewer.render();
        const pixels = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        const colors = new Set();
        let warm = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          colors.add((pixels[i] << 16) + (pixels[i+1] << 8) + pixels[i+2]);
          if (pixels[i] > pixels[i+1] + 12) warm++;
        }
        return {renderer, vendor: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL), warm, colors: colors.size,
          width: canvas.width, height: canvas.height, error: gl.getError()};
      });
      assert.match(backend.renderer, /NVIDIA.*Vulkan/i);
      assert.ok(backend.colors > 100 && backend.warm > 1000 && backend.error === 0);
      const cdp = await context.newCDPSession(page);
      await cdp.send("Performance.enable");
      const loadMetrics = await cdp.send("Performance.getMetrics");
      const resources = await page.evaluate(() => performance.getEntriesByType("resource").map(r => (
        {name: r.name, bytes: r.encodedBodySize, transferred: r.transferSize, duration: r.duration})));
      assert.equal(resources.filter(r => r.name.includes("/api/pack/")).length, 0);
      assert.equal(resources.filter(r => r.name.includes("/api/whole/motion.glb/")).length, 1);
      const samplesMs = await page.evaluate(async () => {
        const panel = document.getElementById("whole-timeline");
        const samples = [];
        for (const i of [0, 27, 55, 83, 110, 0]) {
          const start = performance.now();
          panel.value = i;
          panel.dispatchEvent(new Event("input"));
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          samples.push(performance.now() - start);
        }
        return samples;
      });
      // Three animated loops per fresh browser context, using the actual playback controls.
      const intervals = await page.evaluate(async () => {
        const button = document.getElementById("whole-play");
        const speed = document.getElementById("whole-speed");
        speed.value = 2;
        const times = [];
        for (let i = 0; i < 3; i++) {
          button.click();
          let previous;
          do {
            const now = await new Promise(requestAnimationFrame);
            if (previous !== undefined) times.push(now - previous);
            previous = now;
          } while (window.hmmViewer.whole.status().playing);
        }
        speed.value = 1;
        return times;
      });
      const afterMetrics = await cdp.send("Performance.getMetrics");
      performance.push({ repeat, firstFrameMs, backend, resources, seekMs: samplesMs, intervals,
        latencyMs: {p01:percentile(intervals,.01), p50:percentile(intervals,.5), p95:percentile(intervals,.95)},
        heapBefore:loadMetrics.metrics, heapAfter:afterMetrics.metrics });
      await write("performance", performance);

      if (repeat === 0) {
        const checks = samples.points.map(s => [s.node, s.vertices]);
        const actual = await page.evaluate(({checks, n, bones}) => {
          const api = window.hmmViewer.whole;
          return Array.from({length: n}, (_, i) => {
            api.seek(i);
            return {f:api.status().frame, points:checks.map(([node, vertices]) => api.sample(node, vertices)),
              mats:checks.slice(0,bones).map(([node]) => api.matrix(node))};
          });
        }, {checks, n:samples.n_frames, bones:geoms.length});
        let max = 0, square = 0, count = 0, nativeMatrixMax = 0;
        const rowMetrics = [];
        for (let i = 0; i < actual.length; i++) {
          const {points, mats, f} = actual[i];
          assert.equal(f.state_index, i);
          assert.match(f.state_sha256, /^[a-f0-9]{64}$/);
          assert.match(f.native_transform_sha256, /^[a-f0-9]{64}$/);
          let frameMax = 0;
          for (let j = 0; j < points.length; j++) {
            for (let k = 0; k < points[j].length; k++) {
              const err = Math.hypot(...points[j][k].map((x, axis) => x - samples.points[j].world_glb_m[i][k][axis]));
              frameMax = Math.max(frameMax, err);
              square += err ** 2;
              count++;
            }
            if (j < mats.length) {
              const geom = geoms[j];
              const m = samples.geom_pose_world_m[geom][i];
              const reorder = [0, 2, 1, 3], signs = [1, 1, -1, 1];
              for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++) {
                nativeMatrixMax = Math.max(nativeMatrixMax,
                  Math.abs(m[reorder[row]][reorder[col]] * signs[row] * signs[col] - mats[j][4*col+row]));
              }
            }
          }
          max = Math.max(max, frameMax);
          rowMetrics.push({ ...f, pointMaxM: frameMax });
        }
        const movement = actual[0].points.flatMap((p,j) => p.map((v,k) =>
          Math.hypot(...v.map((x,d) => x-actual[55].points[j][k][d]))));
        assert.ok(Math.max(...movement) > .24 && movement.filter(x => x > .01).length > 500);
        await write("parity", {max, rms:Math.sqrt(square/count), nativeMatrixMax, count,
          movementMaxM:Math.max(...movement), movedOverOneCm:movement.filter(x => x > .01).length, rowMetrics});
        assert.ok(max < cubeTolerance && nativeMatrixMax < cubeTolerance, JSON.stringify({max,nativeMatrixMax}));
        for (const [phase, i] of [["start",0], ["bottom",55], ["return",110]]) {
          await page.evaluate(i => window.hmmViewer.whole.seek(i), i);
          await page.locator("#view").screenshot({ path: `${directory}/browser-side-${phase}.png` });
        }
        await page.evaluate(() => window.hmmViewer.whole.seek(55));
        await page.locator("#whole-camera").selectOption("oblique");
        await page.locator("#view").screenshot({ path: `${directory}/browser-oblique-bottom.png` });
        await page.locator("#whole-camera").selectOption("torso");
        await page.locator("#view").screenshot({ path: `${directory}/browser-torso-bottom.png` });
        const muscles = page.locator('#whole-layers input[value="MUSCLES"]');
        const overlay = page.locator('#whole-layers input[value="OVERLAYS"]');
        await overlay.check();
        await muscles.uncheck();
        await page.locator("#whole-camera").selectOption("side");
        assert.equal(await page.locator('#whole-layers input[value="SKIN"]').isDisabled(), true);
        assert.equal(await page.locator('#whole-layers input[value="ORGANS"]').isDisabled(), true);
        await page.locator("#view").screenshot({ path: `${directory}/browser-skeleton-bottom.png` });
        const save = page.waitForEvent("download");
        await page.locator("#export").click();
        await (await save).saveAs(`${directory}/saved-view.json`);
        const saved = JSON.parse(await fs.readFile(`${directory}/saved-view.json`));
        assert.equal(saved.state_index, 55);
        await page.locator("#whole-static").click();
        await page.waitForFunction(() => window.hmmViewer.getScene().scene === "whole-anterior");
        await page.locator("#import").setInputFiles(`${directory}/saved-view.json`);
        await page.waitForFunction(() => window.hmmViewer.getScene().state_index === 55);
        const restored = await page.evaluate(() => window.hmmViewer.getScene());
        assert.deepEqual(restored.layers, saved.layers);
        for (let i=0;i<3;i++) assert.ok(Math.abs(restored.camera.position[i]-saved.camera.position[i]) < 1e-8);
      }
      await context.close();
    }
    assert.deepEqual(faults, []);
    console.log(JSON.stringify({status:"PASS", hardware: performance[0].backend, freshContexts: performance.length}));
  } finally {
    await browser.close();
  }
}
run().catch(e => { console.error(e); process.exitCode = 1; });
