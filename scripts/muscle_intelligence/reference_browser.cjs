/** Exercise the installed inspector on the existing whole-body viewer. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

async function exerciseEditor(page, editor, exportTestPath) {
  const canvas = editor.locator("canvas");
  async function place(frame) {
    await editor.getByRole("combobox", {name: "Coordinate frame"}).selectOption(frame);
    const coordinates = editor.locator("[data-coordinates]");
    for (const [x, y] of [[.5,.5],[.44,.5],[.56,.5],[.5,.44],[.5,.56],[.35,.5],[.65,.5]]) {
      const {width, height} = await canvas.boundingBox();
      await canvas.click({position:{x:width*x,y:height*y}});
      const text = await coordinates.textContent();
      if (frame === "source" ? !text.includes("Source (mm): pending") : !text.includes("Target (m): pending")) return;
    }
    throw new Error("No surface hit in the pinned example");
  }
  await place("source");
  await place("target");
  await editor.getByLabel("Uncertainty (mm)").fill("1");
  await editor.getByLabel("Reviewer ID as supplied").fill("ENGINEERING_UI_TEST");
  await editor.getByRole("button", {name:"Append candidate"}).click();
  const message = editor.locator("[data-message]");
  assert.match(await message.textContent(), /candidate appended/);
  await editor.getByRole("button", {name:"Withdraw selected landmark"}).click();
  assert.match(await message.textContent(), /Withdrawal appended/);
  await editor.getByRole("button", {name:"Restore selected version"}).click();
  assert.match(await message.textContent(), /Restoration appended/);
  const downloaded = page.waitForEvent("download");
  await editor.getByRole("button", {name:"Export annotation history"}).click();
  const data = await fs.readFile(await (await downloaded).path());
  const exported = JSON.parse(data);
  if (exportTestPath) await fs.writeFile(exportTestPath, data, {flag:"wx"});
  assert.deepEqual(exported.decisions.map(d => d.decision), ["USE_FOR_COMPARISON", "WITHDRAW", "USE_FOR_COMPARISON"]);
  page.once("dialog", dialog => dialog.accept());
  await editor.locator("[data-load]").setInputFiles({name:"test.json", mimeType:"application/json", buffer:data});
  await page.waitForFunction(() => document.querySelector("[data-message]").textContent.includes("History reopened"));
  return {engineering_only:true, clicks_both_frames:true, decision_actions:exported.decisions.map(d=>d.decision),
    export_reopen:true, source_citation_present:exported.correspondences[0].source_evidence.startsWith("https://")};
}

(async () => {
  const [origin, out] = process.argv.slice(2);
  const {views} = JSON.parse(await fs.readFile(out + "/registration-selections.json"));
  const browser = await chromium.launch({args:["--use-gl=angle","--use-angle=vulkan","--enable-features=Vulkan",
    "--disable-vulkan-surface","--no-sandbox"]});
  const result = [], messages = [], inspection = [];
  try {
    for (const mobile of [false, true]) {
      const context = await browser.newContext({viewport:mobile ? {width:390,height:844} : {width:1440,height:920},
        isMobile:mobile, hasTouch:mobile, deviceScaleFactor:mobile ? 2 : 1.5});
      const page = await context.newPage();
      const errors = [], outside = [];
      page.on("pageerror", error => errors.push(error.message));
      page.on("console", msg => {
        messages.push({mobile, type:msg.type(), text:msg.text()});
        if (msg.type() === "error") errors.push(msg.text());
      });
      page.on("request", r => { if (!r.url().startsWith(origin + "/") && !r.url().startsWith("blob:")) outside.push(r.url()); });
      await page.goto(origin + "/?motion=whole");
      await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400);
      const backend = await page.evaluate(() => {
        const gl = document.querySelector("#view").getContext("webgl2");
        return gl.getParameter(gl.getExtension("WEBGL_debug_renderer_info").UNMASKED_RENDERER_WEBGL);
      });
      assert.match(backend, /NVIDIA.*Vulkan/i);
      assert.equal(await page.evaluate(() => window.hmmViewer.whole.muscleNodes().length), 290);
      const panel = page.locator("#registration-evidence");
      const status = panel.locator(":scope > [role=status]");
      const summary = panel.locator(":scope > summary");
      const prefix = mobile ? "mobile" : "desktop";
      await page.locator("#view").scrollIntoViewIfNeeded();
      await page.screenshot({path:out+"/browser/"+prefix+"-overview.png",fullPage:mobile});
      const overview = await page.evaluate(() => window.hmmViewer.getScene());
      inspection.push({mobile, kind:"overview", screenshot:prefix+"-overview.png", view:overview});
      for (const label of (mobile ? ["pectoral","negative-oblique"] :
        ["pectoral","deep-shoulder","lower-leg","negative-oblique"])) {
        const view = views[label];
        const current = await page.evaluate(() => window.hmmViewer.getScene());
        const scene = {...current, muscle:view.selection, state_index:55};
        await page.locator("#import").setInputFiles({name:"view.json",mimeType:"application/json",
          buffer:Buffer.from(JSON.stringify(scene))});
        await panel.waitFor({state:"visible"});
        if (await panel.getAttribute("open") === null) await summary.click();
        const frames = label === "pectoral" ? [0,27,55,83,110] : [55];
        for (const index of frames) {
          await page.evaluate(i => window.hmmViewer.whole.seek(i), index);
          await page.waitForFunction(({index,label}) => {
            const text = document.querySelector("#registration-evidence [role=status]").textContent;
            return text.includes(`#${index} ·`) && text.includes(label) && text.includes("NOT_VERIFIED");
          }, {index, label: view.asset.name});
          const state = await page.evaluate(() => window.hmmViewer.whole.status().frame);
          assert.equal(state.state_index, index);
          const text = await panel.textContent();
          if (label === "negative-oblique") {
            assert.match(text, /GEOMETRY_ONLY/);
            assert.doesNotMatch(text, /Cyan|held-out RMS/);
            assert.equal(await page.locator("#muscle-readings").isVisible(), false);
          } else {
            assert.match(text, /Cyan.*held-out proxies/);
            assert.match(text, /geometric held-out RMS/);
            await page.waitForFunction(() => document.querySelector("#muscle-chart polyline"));
            if (label === "pectoral") {
              const choice = panel.getByRole("combobox", {name: "Bone candidate"});
              assert.ok(await choice.locator("option").count() >= 4);
              await choice.selectOption("FJ3362");
            }
          }
          await page.locator("#muscle-focus").click();
          await page.locator("#view").scrollIntoViewIfNeeded();
          let boneMatrix;
          if (label === "pectoral") {
            boneMatrix = await page.evaluate(async ({ index, source }) => {
              const { request } = await import("/lab_bridge.js");
              const data = await request("muscle.registration", {
                run_id:source.run_id, motion_sha256:source.motion_sha256, state_index:index,
                mapping_revision_sha256:source.mapping_revision_sha256, actuator_id:122,
                evidence_frame:"mujoco_world_m",
              });
              const bone = data.evidence.bones.find(b => b.native?.name === "clavicle");
              return {frame:data.frame, node:bone.native.node,
                matrix:window.hmmViewer.whole.matrix(bone.native.node),
                route:data.evidence.routes.find(r=>r.name==="PECM1_r"), pair:bone.alternatives[0],
                revision:data.evidence.revision_sha256};
            }, {index, source:view.registration});
          }
          const path = `${out}/browser/${mobile?"mobile":"desktop"}-${label}-${index}.png`;
          await page.screenshot({path, fullPage:mobile});
          result.push({mobile, label, state_index:index, time_s:state.frame_time,
            status:await status.textContent(), screenshot:path.split("/").at(-1), backend, boneMatrix,
            run_id:view.registration.run_id, motion_sha256:view.registration.motion_sha256,
            camera:await page.evaluate(() => window.hmmViewer.getScene().camera)});
        }
      }
      const pectoral = views.pectoral;
      const current = await page.evaluate(() => window.hmmViewer.getScene());
      await page.locator("#import").setInputFiles({name:"view.json",mimeType:"application/json",
        buffer:Buffer.from(JSON.stringify({...current,muscle:pectoral.selection,state_index:55}))});
      await page.waitForFunction(() => document.querySelector("#registration-evidence > [role=status]")
        .textContent.includes("Clavicular part of right pectoralis major"));
      await panel.getByRole("combobox", {name:"Bone candidate"}).selectOption("FJ3362");
      const editor = panel.locator("details").filter({hasText:"Named landmark annotation"});
      await editor.locator("summary").click();
      await page.waitForFunction(() => document.querySelector("[data-message]").textContent.includes("meshes loaded"));
      await editor.locator("[data-stage]").scrollIntoViewIfNeeded();
      const stage = editor.locator("[data-stage]");
      const sourceCamera = JSON.parse(await stage.getAttribute("data-camera"));
      await stage.screenshot({path:out+"/browser/"+prefix+"-bone-source.png",scale:"device"});
      await editor.getByRole("combobox", {name:"Coordinate frame"}).selectOption("target");
      const targetCamera = JSON.parse(await stage.getAttribute("data-camera"));
      await stage.screenshot({path:out+"/browser/"+prefix+"-bone-target.png",scale:"device"});
      await editor.screenshot({path:out+"/browser/"+prefix+"-bone-inspector.png",scale:"device"});
      inspection.push({mobile,kind:"bone-pair",state_index:55,FJ:"FJ3362", target:"clavicle",
        sourceCamera, targetCamera, run_id:pectoral.registration.run_id, motion_sha256:pectoral.registration.motion_sha256,
        screenshot_source:prefix+"-bone-source.png", screenshot_target:prefix+"-bone-target.png",
        screenshot_inspector:prefix+"-bone-inspector.png"});
      if (!mobile) inspection.push({mobile,kind:"workflow", ...await exerciseEditor(page,editor,process.env.HMM_ENGINEERING_TEST_EXPORT)});
      assert.deepEqual(errors, []);
      assert.deepEqual(outside, []);
      await context.close();
    }
  } finally {
    await fs.writeFile(out + "/browser/inspector-controls.json", JSON.stringify(inspection, null, 2));
    await fs.writeFile(out + "/browser/console.json", JSON.stringify(messages, null, 2));
    await browser.close();
  }
  await fs.writeFile(out + "/browser/reference-browser.json", JSON.stringify(result, null, 2));
  console.log(`PASS ${result.length} exact inspector views, desktop/mobile emulation, NVIDIA Vulkan, no outside requests.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
