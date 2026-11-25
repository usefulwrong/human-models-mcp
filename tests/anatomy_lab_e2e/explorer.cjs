/** Real atlas workflow, same-scene performance comparison, and detached-source pick. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");
const [origin, baseline, output, matchedScene] = process.argv.slice(2);
const gpu = process.env.HMM_BROWSER_GPU === "1";
const graphics = gpu ? ["--use-gl=angle", "--use-angle=vulkan", "--enable-features=Vulkan", "--disable-vulkan-surface"] :
  ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"];
const desktop = {viewport:{width:1280,height:900}};
const mobile = {viewport:{width:390,height:844},isMobile:true,hasTouch:true};
const write = (name, value) => fs.writeFile(output + "/" + name, JSON.stringify(value,null,2)+"\n");
const scene = page => page.evaluate(() => window.hmmViewer.getScene());
const paint = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
const selection = (page, fma) => page.waitForFunction(id => window.hmmViewer?.getScene().selection[0] === id, fma);
const screenshot = (page, name) => page.screenshot({path: output + "/visual/" + name + ".png"});
const query = (page, request) => page.evaluate(async request => {
  const response = await fetch("/api/query", {method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify(request)});
  return response.json();
}, request);
const settled = async page => {
  await page.waitForFunction(() => window.hmmViewer?.stats().revision > 0);
  await paint(page);
};
async function save(page, path) {
  const download = page.waitForEvent("download");
  await page.locator("#export").click();
  await (await download).saveAs(path);
  return JSON.parse(await fs.readFile(path));
}
async function open(page, files) {
  await page.locator("#import").setInputFiles(files);
}
async function byName(page, name, fma) {
  await page.locator("#query").fill(name);
  await page.locator(`#matches [data-fma=${fma}]`).click();
  await selection(page,fma);
  await paint(page);
}
async function glRenderer(page) {
  return page.evaluate(() => {
    const gl = document.querySelector("#view").getContext("webgl2");
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
  });
}
async function measure(page, from = 0) {
  const resources = await page.evaluate(start => performance.getEntriesByType("resource")
    .filter(r => r.startTime >= start).map(r => ({path:new URL(r.name).pathname, bytes:r.encodedBodySize,
      transferBytes:r.transferSize, durationMs:r.duration})), from);
  const packs = resources.filter(r => r.path.startsWith("/api/pack/"));
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const {metrics} = await cdp.send("Performance.getMetrics");
  await cdp.detach();
  return {packCount:packs.length,glbBytes:packs.reduce((a,r) => a+r.bytes,0),
    jsHeapBytes:metrics.find(m => m.name === "JSHeapUsedSize")?.value, resources};
}
async function browserMemory(browser) {
  const cdp = await browser.newBrowserCDPSession();
  try {
    const {processInfo} = await cdp.send("SystemInfo.getProcessInfo");
    return Promise.all(processInfo.map(async ({type,id}) => {
      const status = await fs.readFile(`/proc/${id}/status`,"utf8").catch(() => "");
      const rss = /^VmRSS:\s+(\d+)/m.exec(status);
      return {type,rssKiB:rss ? Number(rss[1]) : "NOT_MEASURED"};
    }));
  } finally { await cdp.detach(); }
}
async function drag(page) {
  const rect = await page.locator("#view").boundingBox();
  await page.evaluate(() => {
    window.frameTimes = [];
    function tick(t) {
      window.frameTimes.push(t);
      if (window.frameTimes.length < 32) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
  await page.mouse.move(rect.x+rect.width*.40,rect.y+rect.height*.50);
  await page.mouse.down();
  await page.mouse.move(rect.x+rect.width*.65,rect.y+rect.height*.44,{steps:24});
  await page.mouse.up();
  await page.waitForFunction(() => window.frameTimes.length === 32);
  return page.evaluate(() => window.frameTimes.slice(1).map((x,i) => x-window.frameTimes[i]));
}
function collect(page, events) {
  page.on("request", r => events.push(["request",r.method(),r.url()]));
  page.on("response", r => events.push(["response",r.status(),r.url()]));
  page.on("requestfailed", r => events.push(["requestfailed",r.failure().errorText,r.url()]));
  page.on("console", m => events.push(["console",m.type(),m.text()]));
  page.on("pageerror", e => events.push(["pageerror",e.message]));
}

async function benchmark(browser) {
  const results = [];
  for (let repeat = 1; repeat <= 3; repeat++) {
    const variants = repeat % 2 ? [["baseline",baseline],["candidate",origin]] :
      [["candidate",origin],["baseline",baseline]];
    for (const [variant,url] of variants) {
      const page = await browser.newPage(desktop);
      try {
        const start = Date.now();
        await page.goto(url);
        await settled(page);
        const entryMs = Date.now()-start;
        const initial = await measure(page);
        const entryFjCount = await page.evaluate(() => window.hmmViewer.visibleFjIds().length);
        const renderer = await glRenderer(page);
        if (gpu) assert.match(renderer,/NVIDIA.*RTX/);
        const searchStart = Date.now();
        await page.locator("#query").fill("heart");
        const heart = page.locator("#matches [data-fma=FMA7088]");
        await heart.waitFor();
        const searchMs = Date.now()-searchStart;
        const mark = await page.evaluate(() => performance.now());
        const selectStart = Date.now();
        await heart.click();
        await selection(page,"FMA7088");
        await paint(page);
        const selectMs = Date.now()-selectStart;
        const selected = await measure(page,mark);
        const firstAnatomyMs = entryFjCount ? entryMs : Date.now()-start;
        await open(page,matchedScene);
        const expected = JSON.parse(await fs.readFile(matchedScene)).camera;
        await page.waitForFunction(expected => {
          const current = window.hmmViewer.getScene().camera;
          return JSON.stringify(current.position) === JSON.stringify(expected.position) &&
            JSON.stringify(current.target) === JSON.stringify(expected.target);
        }, expected);
        await paint(page);
        if (repeat === 1) await screenshot(page,`matched-${variant}-heart-desktop`);
        const before = await scene(page);
        const frameIntervalsMs = await drag(page);
        assert.notDeepEqual((await scene(page)).camera.position,before.camera.position);
        results.push({repeat, variant, renderer, entryMs, initial, entryFjCount, searchMs, selectMs, selected,
          firstAnatomyMs, actions:2, sameSavedCamera:true, frameIntervalsMs, browserMemory:await browserMemory(browser)});
      } finally { await page.close(); }
    }
  }
  return results;
}

async function functional(browser) {
  const page = await browser.newPage(desktop);
  const events = [];
  collect(page,events);
  try {
    await page.goto(origin);
    await settled(page);
    assert.equal((await scene(page)).scene,"whole-anterior");
    assert.equal(await page.evaluate(() => window.hmmViewer.visibleFjIds().length),1);
    await screenshot(page,"final-entry-desktop");
    await page.locator("#display summary").click();
    const overviewBones = page.getByRole("checkbox",{name:"Bones",exact:true});
    const atlasLayers = output + "/scenes/overview-layers.json";
    assert.equal(await overviewBones.isEnabled(),true);
    await overviewBones.check();
    await page.waitForFunction(() => window.hmmViewer.visibleFjIds().length === 380);
    await paint(page);
    await screenshot(page,"overview-bones-desktop");
    const overviewSaved = await save(page,atlasLayers);
    assert.deepEqual(overviewSaved.visible_layers,["skin","bone"]);
    await overviewBones.uncheck();
    assert.equal(await page.evaluate(() => window.hmmViewer.visibleFjIds().length),1);
    await page.reload();
    await settled(page);
    await open(page,atlasLayers);
    await page.waitForFunction(() => window.hmmViewer.visibleFjIds().length === 380);
    assert.deepEqual((await scene(page)).visible_parts,overviewSaved.visible_parts);
    await page.locator("#query").focus();
    await page.keyboard.type("left lung");
    await page.locator("#matches [data-fma=FMA7310]").waitFor();
    assert.match(await page.locator("#matches [data-fma=FMA7310]").innerText(),/Patient left/);
    await page.keyboard.press("Enter");
    assert.ok(await page.locator("#matches button").first().evaluate(e => e === document.activeElement));
    await page.keyboard.press("Enter");
    await selection(page,"FMA7310");
    await page.locator("#isolate").click();
    await page.getByRole("button",{name:"Restore context"}).waitFor();
    await paint(page);

    const source = await browser.newPage(desktop);
    let detached, sourcePixel;
    try {
      await source.goto(baseline);
      await settled(source);
      await byName(source,"left lung","FMA7310");
      await source.locator("#isolate").click();
      await paint(source);
      sourcePixel = [328,414];
      [detached] = await source.evaluate(([x,y]) => window.hmmViewer.pick(x,y),sourcePixel);
      assert.match(detached,/^FJ/);
    } finally { await source.close(); }

    const rect = await page.locator("#view").boundingBox();
    let position = await page.evaluate(({rect,detached}) => {
      for (let x = rect.width*.15; x < rect.width*.53; x+=3) {
        for (let y = rect.height*.25; y < rect.height*.6; y+=5) {
          if (window.hmmViewer.pick(rect.x+x,rect.y+y)[0] === detached) return [rect.x+x,rect.y+y];
        }
      }
      return null;
    }, {rect,detached});
    assert.ok(position, "detached source object must be pickable");
    await page.mouse.click(...position);
    await page.waitForFunction(id => document.querySelector("#constituent-info").textContent.startsWith(id),
      detached);
    await page.getByText("Mesh source records",{exact:true}).waitFor();
    assert.equal(await page.locator("#constituent").inputValue(),detached);
    await screenshot(page,"final-left-lung-detached-desktop");
    const rep = {dataset:"BodyParts3D",mesh_version:"4.3",membership_version:"4.3+4.3i"};
    const identity = await query(page,{operation:"anatomy.identify",mesh:detached,representation:rep});
    assert.equal(identity.mesh.id,detached);
    assert.ok(identity.candidate_count > 1);
    await page.locator("#isolate").click();
    await page.locator("#display summary").click();
    const bones = page.locator('#layers input[value="bone"]');
    const withContext = await page.evaluate(() => window.hmmViewer.visibleFjIds().length);
    await bones.uncheck();
    const withoutBones = await page.evaluate(() => window.hmmViewer.visibleFjIds().length);
    assert.ok(withContext > withoutBones);
    await page.locator("#opacity").fill("45");
    const onDisk = output + "/scenes/left-lung-explorer.json";
    const saved = await save(page,onDisk);
    assert.deepEqual(saved.composite_view.hidden_layers,["bone"]);
    assert.equal(saved.composite_view.context_opacity,.45);
    assert.equal(saved.composite_view.inspected_fj,detached);
    await page.reload();
    await settled(page);
    await open(page,onDisk);
    await selection(page,"FMA7310");
    assert.equal(await page.evaluate(() => window.hmmViewer.visibleFjIds().length),withoutBones);
    const again = await save(page,output+"/scenes/left-lung-explorer-reimported.json");
    assert.deepEqual(again,saved);
    await open(page,{name:"stale.json",mimeType:"application/json",
      buffer:Buffer.from(JSON.stringify({...saved,atlas_sha256:"0".repeat(64)}))});
    await page.getByText("scene belongs to a different atlas catalog",{exact:true}).waitFor();
    assert.deepEqual((await scene(page)).selection,["FMA7310"]);

    await page.getByRole("button",{name:"Skeletal",exact:true}).click();
    await page.getByRole("button",{name:/Skeleton \(in vivo\)/i}).click();
    await page.getByText("Skeleton (in vivo)",{exact:true}).waitFor();
    await page.getByRole("button",{name:"Back",exact:true}).click();
    await page.getByRole("button",{name:"Rib cage",exact:true}).click();
    await selection(page,"FMA7480");
    await screenshot(page,"final-skeletal-desktop");

    await page.getByRole("button",{name:"Muscular",exact:true}).click();
    assert.equal(await page.locator("#hierarchy").inputValue(),"IS-A");
    await page.getByRole("button",{name:"Shoulder muscles",exact:true}).click();
    await selection(page,"FMA33531");
    await screenshot(page,"final-muscular-desktop");
    for (const system of ["Nervous","Respiratory","Circulatory","Digestive","Urinary","Endocrine","Integumentary"]) {
      await page.getByRole("button",{name:system,exact:true}).click();
      await page.locator("#branch strong").waitFor();
      await page.locator("#relations").getByRole("heading",{name:"Children"}).waitFor();
      await page.waitForFunction(() => document.querySelectorAll("#relations ul").length === 2 &&
        [...document.querySelectorAll("#relations ul")].every(n => n.childElementCount > 0));
    }
    await page.locator("#query").fill(detached.toLowerCase());
    await page.locator(`#matches [data-fj=${detached}]`).click();
    await page.getByText("Mesh source records",{exact:true}).waitFor();
    await page.waitForFunction(id => window.hmmViewer.visibleFjIds()[0] === id, detached);
    await page.locator("#query").fill("FMA999999999");
    await page.getByText(/absent from the installed catalog/).waitFor();
    await screenshot(page,"final-unknown-desktop");
    assert.equal(events.filter(r => r[0] === "request" && !r[2].startsWith(origin + "/")).length,0);
    assert.equal(events.filter(r => r[0] === "pageerror" || r[0] === "requestfailed").length,0);
    const phone = await browser.newPage(mobile);
    try {
      await phone.goto(origin);
      await settled(phone);
      assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth),390);
      await screenshot(phone,"final-entry-mobile");
      await phone.locator("#display summary").tap();
      await phone.getByRole("checkbox",{name:"Bones",exact:true}).tap();
      await phone.waitForFunction(() => window.hmmViewer.visibleFjIds().length === 380);
      await phone.getByRole("checkbox",{name:"Bones",exact:true}).tap();
      assert.equal(await phone.evaluate(() => window.hmmViewer.visibleFjIds().length),1);
      await phone.getByRole("button",{name:"Heart",exact:true}).tap();
      await selection(phone,"FMA7088");
      await paint(phone);
      await screenshot(phone,"final-heart-mobile");
      const box = await phone.locator("#view").boundingBox();
      const point = [box.x+box.width/2,box.y+box.height/2];
      const [hit] = await phone.evaluate(([x,y]) => window.hmmViewer.pick(x,y),point);
      assert.match(hit,/^FJ/);
      await phone.touchscreen.tap(...point);
      await phone.waitForFunction(id => document.querySelector("#constituent-info").textContent.startsWith(id),hit);
      await phone.getByText("Mesh source records",{exact:true}).waitFor();
    } finally { await phone.close(); }
    return {status:"PASS",detached,sourcePixel,position,record:identity.mesh,candidateCount:identity.candidate_count,
      withContext,withoutBones,desktopRenderer:await glRenderer(page), events,
      cases:["anterior preview", "on-demand atlas layers + replay", "keyboard search + laterality","source-backed children + back","nine installed root entries",
        "real ray pick and FJ search","layer/opacity/context/highlight replay","stale catalog rejection",
        "missing concept","skeletal + muscular","mobile viewport and emulated touch","browser network origin"]};
  } finally {
    await write("logs/explorer-events.json",events);
    await page.close();
  }
}

(async () => {
  for (const folder of ["visual","logs","scenes"]) await fs.mkdir(output+"/"+folder,{recursive:true});
  const browser = await chromium.launch({channel:process.env.HMM_BROWSER_CHANNEL || undefined,
    args:[...graphics,"--disable-background-networking","--no-proxy-server"]});
  try {
    if (process.env.HMM_BENCHMARK_ONLY !== "1") await write("explorer-results.json",await functional(browser));
    if (process.env.HMM_SKIP_BENCHMARK !== "1") {
      await write("explorer-performance.json",{browser:browser.version(),node:process.version,
        playwright:require("playwright/package.json").version,rows:await benchmark(browser)});
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e);process.exitCode=1});
