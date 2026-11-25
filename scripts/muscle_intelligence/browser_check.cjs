/** Real point picking, exact signal cursor, reload and left/right on Chromium. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");
const [origin, out] = process.argv.slice(2);
const evidence = out + "/browser";
const pause = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
const state = page => page.evaluate(() => window.hmmViewer.whole.status().frame.state_index);
const frameRate = page => page.evaluate(async () => {
  const play = document.getElementById("whole-play");
  play.click();
  let frames = 0;
  const start = performance.now();
  while (performance.now() - start < 600) {
    await new Promise(requestAnimationFrame);
    frames++;
  }
  play.click();
  return 1000 * frames / (performance.now() - start);
});

async function pick(page, candidates) {
  const hit = await page.evaluate(ids => {
    const api = window.hmmViewer.whole;
    const canvas = document.getElementById("view").getBoundingClientRect();
    for (const id of ids) {
      const points = api.project(api.faceCenters(id).filter((_, i) => i % 7 === 0));
      for (const [x,y] of points) {
        if (x < canvas.left + 5 || x > canvas.right - 5 || y < canvas.top + 60 || y > canvas.bottom - 85) continue;
        if (api.muscleHit(x,y) === id) return {x,y,id};
      }
    }
    return null;
  }, candidates);
  return hit;
}

async function importView(page, view) {
  await page.locator("#import").setInputFiles({name:"anatomy-scene.json", mimeType:"application/json",
    buffer:Buffer.from(JSON.stringify(view))});
  await page.waitForFunction(target => {
    const v = window.hmmViewer.getScene();
    return v.camera?.position?.every((val, i) => Math.abs(val - target[i]) < 1e-8);
  }, view.camera.position, {timeout: 20000});
  await pause(page);
}

(async () => {
  const transport = JSON.parse(await fs.readFile(out + "/transport.json"));
  const audit = JSON.parse(await fs.readFile(out + "/ALL_ACTUATOR_SIGNAL_AUDIT.json"));
  const controls = JSON.parse(await fs.readFile(out + "/selection-controls.json"));
  const browser = await chromium.launch({args: ["--use-gl=angle", "--use-angle=vulkan",
    "--enable-features=Vulkan", "--disable-vulkan-surface", "--no-sandbox"]});
  const summary = [];
  try {
    for (const mobile of [false, true]) {
      const label = mobile ? "mobile" : "desktop";
      const context = await browser.newContext({viewport: mobile ? {width:390,height:844} : {width:1440,height:900},
        isMobile: mobile, hasTouch: mobile, acceptDownloads: true});
      const page = await context.newPage();
      const errors = [], external = [];
      const queries = [];
      page.on("pageerror", e => errors.push(e.message));
      page.on("request", req => {
        if (!req.url().startsWith(origin) && !req.url().startsWith("blob:")) external.push(req.url());
        if (req.url() === origin + "/api/query" && req.method() === "POST") queries.push(req.postDataJSON().operation);
      });
      const t = Date.now();
      await page.goto(origin + "/?motion=whole");
      await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400, null, {timeout:25000});
      await pause(page);
      const firstFrameMs = Date.now() - t;
      assert.equal(queries.filter(op=>op==="muscle.timeseries").length, 0);
      const nodes = await page.evaluate(() => window.hmmViewer.whole.muscleNodes().sort((a,b) => a-b));
      assert.deepEqual(nodes, audit.display_node_ids_resolved);
      const rays = await page.evaluate(() => window.hmmViewer.whole.muscleRayAudit());
      assert.equal(rays.length, nodes.length);
      await fs.writeFile(evidence+"/"+label+"-node-audit.json", JSON.stringify(rays,null,2));
      assert.deepEqual(rays.filter(row => !row.ray_hits_isolated_mesh), []);
      const firstDraw = await page.evaluate(() => window.hmmViewer.stats());
      const fullSceneFps = await frameRate(page);
      await page.evaluate(() => window.hmmViewer.whole.seek(0));
      const backend = await page.evaluate(() => {
        window.hmmViewer.render();
        const canvas = document.querySelector("#view");
        const gl = canvas.getContext("webgl2");
        const debug = gl.getExtension("WEBGL_debug_renderer_info");
        const p = new Uint8Array(4);
        gl.readPixels(canvas.width >> 1, canvas.height >> 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, p);
        return {renderer:gl.getParameter(debug.UNMASKED_RENDERER_WEBGL), pixel:Array.from(p),
          dimensions:[canvas.width, canvas.height], error:gl.getError()};
      });
      assert.match(backend.renderer, /NVIDIA.*Vulkan/i);
      assert.equal(backend.error, 0);
      const cdp = await context.newCDPSession(page);
      await cdp.send("Performance.enable");
      for (const box of await page.locator('#whole-layer-options input:checked').all()) {
        if (await box.getAttribute("value") !== "MUSCLES") await box.uncheck();
      }
      await page.locator("#whole-camera").selectOption("chest_right");
      await pause(page);
      await page.locator("#view").scrollIntoViewIfNeeded();
      let hit = await pick(page, [239,496]);
      if (!hit || hit.id !== 239) {
        const result = await page.evaluate(async () => {
          const api = window.hmmViewer.whole;
          const notes = [];
          const face = api.faceCenters(239).filter((_, i) => i % 9 === 0);
          const center = face.reduce((acc,p) => acc.map((v,i) => v+p[i]/face.length), [0,0,0]);
          for (const x of [1.38,1.9,.85]) for (const y of [.055,.25,.70,1.13]) for (const z of [.60,1.12,-.7]) {
            const candidate = {position:[x,y,z],target:center,fov:36};
            api.diagnosticCamera(candidate);
            window.hmmViewer.render();
            const box = document.getElementById("view").getBoundingClientRect();
            const hits = {};
            for (const [px,py] of api.project(face)) {
              if (px <= box.left+15 || px >= box.right-15 || py <= box.top+55 || py >= box.bottom-90) continue;
              const row = api.muscleHit(px,py,true);
              if (row?.node === 239) return {hit:{x:px,y:py,id:239},candidate,notes,center};
              if (row) hits[row.name] = (hits[row.name] || 0) + 1;
            }
            notes.push({candidate,hits});
          }
          return {notes,center};
        });
        await fs.writeFile(evidence+"/"+label+"-pick-debug.json", JSON.stringify(result,null,2));
        hit = result.hit;
      }
      assert.ok(hit, "right pectoralis visibly pickable");
      await (mobile ? page.touchscreen.tap(hit.x,hit.y) : page.mouse.click(hit.x,hit.y));
      await page.waitForFunction(() => document.getElementById("muscle-axes").textContent.includes("111 states"));
      assert.match(await page.locator("#muscle-identity").textContent(), /right · FMA34690/);
      assert.match(await page.locator("#muscle-note").textContent(), /NOT_ACHIEVED.*USED.*NOT_VALIDATED.*EMG/);
      assert.equal(await page.locator("#muscle-chart polyline").count(), 1);
      await page.locator("#muscle-metric").selectOption("force_N");
      await page.waitForFunction(() => document.getElementById("muscle-aggregation").textContent.includes("signed"));
      await page.locator("#muscle-chart").scrollIntoViewIfNeeded();
      const rect = await page.locator("#muscle-chart").boundingBox();
      await page.locator("#muscle-chart").click({position:{x:rect.width/2,y:rect.height/2}});
      assert.equal(await state(page), 55);
      const native = transport["pectoralis_major:right"].entries.force_N;
      assert.match(await page.locator("#muscle-value").textContent(), /#55.*bottom.*exact pose/);
      assert.ok((await page.locator("#muscle-value").textContent()).includes(native.aggregate[55].toPrecision(6)));
      const frame = await page.evaluate(() => window.hmmViewer.getScene());
      const latencies = await page.evaluate(async () => {
        const data = [];
        for (const i of [27,55,83,110,0,55]) {
          const t = performance.now();
          const input = document.getElementById("whole-timeline");
          input.value = i;
          input.dispatchEvent(new Event("input"));
          if (!document.getElementById("muscle-value").textContent.startsWith("#"+i+" ")) throw Error("cursor mismatch");
          data.push(performance.now()-t);
        }
        return data;
      });
      await page.locator("#muscle-path").selectOption("122");
      await page.waitForFunction(() => document.getElementById("muscle-aggregation").textContent === "PECM1_r");
      assert.match(await page.locator("#muscle-value").textContent(), /PECM1_r/);
      assert.doesNotMatch(await page.locator("#muscle-value").textContent(), /PECM2_r/);
      await page.locator("#muscle-path").selectOption("");
      const material = await page.evaluate(() => window.hmmViewer.whole.muscleColor(239));
      await page.locator("#muscle-overlay").check();
      await page.waitForFunction(() => document.getElementById("muscle-legend").textContent.includes("blue to 1 gold"));
      const rgb = await page.evaluate(() => window.hmmViewer.whole.muscleColor(239));
      assert.deepEqual(rgb, transport["pectoralis_major:right"].selection.overlay.linear_rgb);
      const samples = JSON.parse(await fs.readFile("/clip/samples.json"));
      const row = samples.points.find(p => p.node === 239);
      const browserPoints = await page.evaluate(v => window.hmmViewer.whole.sample(239,v), row.vertices);
      assert.ok(Math.max(...browserPoints.flatMap((vec,k)=>vec.map((v,j)=>Math.abs(v-row.world_glb_m[55][k][j])))) < .0001);
      if (!mobile) {
        await page.locator("#whole-timeline").scrollIntoViewIfNeeded();
        await page.screenshot({path:evidence+"/desktop-pectoralis-bottom.png"});
        await fs.writeFile(evidence+"/browser-parity.json",JSON.stringify({node:239,state:55,rgb,browserPoints}));
      } else {
        await page.screenshot({path:evidence+"/mobile-inspector.png",fullPage:true});
      }
      const resources = await page.evaluate(() => performance.getEntriesByType("resource").map(r => ({
        path:new URL(r.name).pathname, bytes:r.transferSize,
      })));
      assert.equal(resources.filter(r=>r.path.startsWith("/api/whole/motion.glb")).length,1);
      const stored = await page.waitForFunction(async () => {
        const view = window.hmmViewer.getScene();
        const response = await fetch("/api/query",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({operation:"muscle.selection",run_id:view.run_id})});
        const value = await response.json();
        return value.selection?.overlay && value.selection.display_node === 239 && value.frame.state_index === 55;
      },null,{polling:300});
      assert.ok(stored);
      await page.locator("#muscle-opacity-scope").selectOption("surface");
      const alpha = value => page.locator("#muscle-opacity").evaluate((el, v) => {
        el.value = v;
        el.dispatchEvent(new Event("change"));
      }, value);
      await alpha(".55");
      await page.waitForFunction(() => window.hmmViewer.whole.muscleState(239).opacity === .55 &&
        window.hmmViewer.whole.muscleState(402).opacity === 1);
      await page.locator("#muscle-opacity-scope").selectOption("source");
      await page.waitForFunction(() => window.hmmViewer.whole.muscleState(402).opacity === .55 &&
        window.hmmViewer.whole.muscleState(516).opacity === 1);
      await alpha("1");
      await page.locator("#muscle-opacity-scope").selectOption("selection");
      await page.locator("#muscle-isolate").check();
      await page.waitForFunction(() => !window.hmmViewer.whole.muscleState(402).visible);
      const download = page.waitForEvent("download");
      await page.locator("#export").click();
      const file = (await download);
      await file.saveAs(evidence + "/" + label + "-view.json");
      const saved = JSON.parse(await fs.readFile(evidence + "/" + label + "-view.json"));
      assert.equal(saved.muscle.display_node,239);
      assert.equal(saved.muscle.isolate,true);
      await page.locator("#muscle-overlay").uncheck();
      await page.waitForFunction(original => JSON.stringify(window.hmmViewer.whole.muscleColor(239)) === JSON.stringify(original), material);
      const cacheStart = Date.now();
      await importView(page, saved);
      await page.waitForFunction(() => document.getElementById("muscle-value").textContent.startsWith("#55 "));
      const cachedReopenMs = Date.now() - cacheStart;
      assert.equal(await page.evaluate(() => performance.getEntriesByType("resource").filter(
        row => new URL(row.name).pathname.startsWith("/api/whole/motion.glb")).length), 1);
      await page.reload();
      await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400);
      await importView(page, saved);
      await page.waitForFunction(() => document.getElementById("muscle-value").textContent.startsWith("#55 "));
      assert.equal(await page.locator("#muscle-overlay").isChecked(),true);
      assert.equal(await page.locator("#muscle-isolate").isChecked(),true);
      assert.equal(await page.evaluate(() => window.hmmViewer.whole.muscleState(402).visible),false);
      await page.waitForFunction(async () => {
        const view = window.hmmViewer.getScene();
        const response = await fetch("/api/query",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({operation:"muscle.selection",run_id:view.run_id})});
        const value = await response.json();
        return value.selection?.isolate && value.selection?.overlay && value.frame.state_index === 55;
      }, null, {polling:300});
      await page.locator("#muscle-sync").click();
      await page.waitForFunction(() => !document.getElementById("muscle-sync").disabled);
      await page.locator("#muscle-isolate").uncheck();
      await page.waitForFunction(() => window.hmmViewer.whole.muscleState(402).visible);
      await page.locator("#whole-restart").click();
      await page.locator("#whole-camera").selectOption("chest_left");
      await pause(page);
      await page.locator("#view").scrollIntoViewIfNeeded();
      const hitLeft = await pick(page,[237]);
      assert.ok(hitLeft, "left pectoralis visibly pickable");
      await (mobile ? page.touchscreen.tap(hitLeft.x,hitLeft.y) : page.mouse.click(hitLeft.x,hitLeft.y));
      await page.waitForFunction(() => document.getElementById("muscle-identity").textContent.includes("left · FMA34691"));
      if (!mobile) {
        await importView(page, {...frame, state_index:55, camera:{position:[1.24,.7,1.1],target:[1.12,.37,0],fov:35}});
        await page.locator("#view").scrollIntoViewIfNeeded();
        let tri = await pick(page,[367,266]);
        if (!tri) {
          await importView(page, {...frame,state_index:55,camera:{position:[.83,.73,1],target:[1.13,.28,0],fov:31}});
          tri = await pick(page,[367,266]);
        }
        assert.ok(tri, "right triceps visibly pickable");
        await page.mouse.click(tri.x,tri.y);
        await page.waitForFunction(() => document.getElementById("muscle-title").textContent.includes("right triceps"));
        await page.waitForFunction(() => document.getElementById("muscle-value").textContent.includes("TRIlong_r"));
        await page.locator("#muscle-metric").selectOption("force_N");
        await page.waitForFunction(() => document.getElementById("muscle-aggregation").textContent.includes("signed"));
        await page.locator("#muscle-overlay").check();
        await page.waitForFunction(() => document.getElementById("muscle-legend").textContent.includes("blue to 1 gold"));
        const triData = transport["triceps_brachii:right"];
        assert.ok((await page.locator("#muscle-value").textContent()).includes(triData.selection.sample.aggregate[0].toPrecision(6)));
        const triRgb = await page.evaluate(node => window.hmmViewer.whole.muscleColor(node), tri.id);
        assert.deepEqual(triRgb, triData.selection.overlay.linear_rgb);
        const triRow = samples.points.find(p => p.node === tri.id);
        const triPoints = await page.evaluate(({node, vertices}) => window.hmmViewer.whole.sample(node,vertices), triRow);
        await fs.writeFile(evidence+"/browser-triceps-parity.json", JSON.stringify({
          node:tri.id,state:55,rgb:triRgb,browserPoints:triPoints,sourceName:triRow.name,
          signed_aggregate_N:triData.selection.sample.aggregate[0]}));
        await page.screenshot({path:evidence+"/desktop-triceps-bottom.png"});
        const layer = page.locator('#whole-layer-options input[value="MUSCLES"]');
        await layer.uncheck();
        assert.equal(await page.evaluate(({x,y})=>window.hmmViewer.whole.muscleHit(x,y),tri),null);
        await layer.check();
      }
      await page.locator("#muscle-browser summary").click();
      await page.waitForFunction(() => document.getElementById("muscle-list-count").textContent.endsWith("of 700"));
      await page.locator("#muscle-next").click();
      await page.waitForFunction(() => document.getElementById("muscle-list-count").textContent.startsWith("21"));
      const submit = () => page.locator('#muscle-search button[type="submit"]').click();
      const nativeOnly = controls.native.native;
      await page.locator("#muscle-query").fill(nativeOnly.exact_name);
      await page.locator("#muscle-filter").selectOption("unmapped");
      await submit();
      const selectNativeStart = Date.now();
      await page.locator(`#muscle-results [data-actuator="${nativeOnly.id}"]`).click();
      await page.waitForFunction(name => document.getElementById("muscle-value").textContent.includes(name), nativeOnly.exact_name);
      const nativeSelectionMs = Date.now() - selectNativeStart;
      await page.evaluate(() => window.hmmViewer.whole.seek(55));
      assert.match(await page.locator("#muscle-identity").textContent(), /UNMAPPED/);
      assert.ok((await page.locator("#muscle-value").textContent()).includes(
        controls.native.sample.series[0].values[0].toPrecision(6)));
      assert.equal(await page.locator("#muscle-overlay").isDisabled(), true);
      assert.equal(await page.locator("#muscle-isolate").isDisabled(), true);
      await page.locator("#muscle-to").fill("2.2");
      await page.locator("#muscle-stride").fill("2");
      await page.locator('#muscle-window button[type="submit"]').click();
      await page.waitForFunction(() => document.getElementById("muscle-axes").textContent.includes("28 states"));
      await page.screenshot({path:evidence+"/"+label+"-native.png",fullPage:mobile});
      await page.locator("#muscle-query").fill("FJ1452");
      await page.locator("#muscle-filter").selectOption("geometry_only");
      await submit();
      await page.locator('#muscle-results [data-node="402"]').click();
      await page.waitForFunction(() => document.getElementById("muscle-identity").textContent.includes("GEOMETRY_ONLY"));
      assert.match(await page.locator("#muscle-identity").textContent(), /FMA13336.*MyoSuite.*ILLUSTRATIVE/);
      assert.equal(await page.locator("#muscle-readings").isVisible(),false);
      await page.locator("#muscle-isolate").check();
      await page.waitForFunction(() => !window.hmmViewer.whole.muscleState(239).visible);
      await page.locator("#muscle-focus").click();
      await page.locator("#view").scrollIntoViewIfNeeded();
      await pause(page);
      await page.screenshot({path:evidence+"/"+label+"-orphan.png",fullPage:mobile});
      await page.locator("#muscle-query").fill("soleus_r");
      await page.locator("#muscle-filter").selectOption("mapped");
      await page.locator("#muscle-region").selectOption("leg_foot");
      await page.locator("#muscle-side").selectOption("right");
      await submit();
      await page.locator('#muscle-results [data-actuator="32"]').click();
      await page.waitForFunction(() => document.getElementById("muscle-value").textContent.includes("soleus_r"));
      const soleus = transport["soleus:right"].entries.activation;
      assert.ok((await page.locator("#muscle-value").textContent()).includes(soleus.series[0].values[55].toPrecision(6)));
      await page.locator("#muscle-isolate").check();
      await page.waitForFunction(() => !window.hmmViewer.whole.muscleState(402).visible &&
        window.hmmViewer.whole.muscleState(457).visible);
      await page.locator("#muscle-focus").click();
      await page.locator("#view").scrollIntoViewIfNeeded();
      await pause(page);
      const legRow = JSON.parse(await fs.readFile("/clip/samples.json")).points.find(row => row.node === 457);
      const legPoints = await page.evaluate(row => window.hmmViewer.whole.sample(row.node, row.vertices),legRow);
      assert.ok(Math.max(...legPoints.flatMap((vec,k)=>vec.map((v,j)=>Math.abs(v-legRow.world_glb_m[55][k][j])))) < .0001);
      if (!mobile) await fs.writeFile(evidence+"/browser-leg-parity.json",JSON.stringify({
        node:457,state:55,points:legPoints,activation:soleus.series[0].values[55],asset:transport["soleus:right"].selection.asset,
      },null,2));
      await page.screenshot({path:evidence+"/"+label+"-leg.png",fullPage:mobile});
      const isolatedFps = await frameRate(page);
      const perf = await cdp.send("Performance.getMetrics");
      assert.deepEqual(errors, []);
      assert.deepEqual(external, []);
      summary.push({label,firstFrameMs,cachedReopenMs,backend,firstDraw,graphSeekCpuMs:latencies,nativeSelectionMs,
        fullSceneFps,isolatedFps,
        nodeCountResolved:nodes.length,resources,metrics:perf.metrics,
        desktopOrMobileRawSelection:true,leftRight:true,reload:true,external});
      await fs.writeFile(evidence+"/browser-results.json", JSON.stringify(summary,null,2));
      await context.close();
      console.log(label,backend.renderer,"PASS",firstFrameMs,"ms first frame");
    }
  } finally {
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
