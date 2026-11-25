/** Verify the same exact selection receipts and comparison geometry in Chromium. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");
const [origin, out] = process.argv.slice(2);

async function inspect(page, label, view, mobile) {
  const info = view.registration;
  const expected = info.rows[0]?.exact_name;
  const current = await page.evaluate(() => window.hmmViewer.getScene());
  const scene = {...current, muscle: view.selection, state_index: view.frame.state_index};
  await page.locator("#import").setInputFiles({name:"view.json",mimeType:"application/json",
    buffer:Buffer.from(JSON.stringify(scene))});
  const details = page.locator("#muscle-inspector details").filter({hasText:"Identity and model route"});
  await page.waitForFunction(({node, id, status, sha, frame, native}) => {
    const whole = window.hmmViewer.whole;
    const text = document.querySelector("#muscle-inspector details").textContent;
    const chosen = window.hmmViewer.getScene().muscle;
    return chosen?.display_node === node && chosen?.actuator_id === id &&
      whole.status().frame.state_index === frame && text.includes(`State #${frame}`) && text.includes(sha)
      && (native ? text.includes(native) : !document.querySelector("#muscle-inspector details li"))
      && document.querySelector("#muscle-identity").textContent.includes(status);
  }, {node:view.selection.display_node,id:view.selection.actuator_id,status:view.mapping_status,
    sha:info.mapping_revision_sha256,frame:view.frame.state_index,native:expected});
  const summary = details.locator("summary");
  if (await details.getAttribute("open") === null) await summary.click();
  if (expected) assert.match(await details.textContent(), new RegExp(expected));
  if (view.asset) {
    const node = view.selection.display_node;
    await page.waitForFunction(n => window.hmmViewer.whole.muscleState(n).visible, node);
  }
  if (label === "negative-oblique") {
    assert.equal(await page.locator("#muscle-readings").isVisible(), false);
    assert.equal(await page.locator("#muscle-overlay").isDisabled(), true);
  } else {
    const target = view.sample.series[0].values[0].toPrecision(6);
    await page.waitForFunction(value => document.getElementById("muscle-value").textContent.includes(value),target);
    assert.equal(await page.locator("#muscle-chart polyline").count(), 1);
  }
  if (view.asset) await page.locator("#muscle-focus").click();
  await page.locator("#view").scrollIntoViewIfNeeded();
  await page.screenshot({path:`${out}/browser/${mobile ? "mobile" : "desktop"}-pilot-${label}.png`,fullPage:mobile});
  return {run_id:info.run_id,motion_sha256:info.motion_sha256,crosswalk_revision:info.crosswalk_revision,
    mapping_revision_sha256:info.mapping_revision_sha256,state_index:info.frame.state_index,time_s:info.frame.frame_time,
    mapping_status:info.mapping_status,native:expected,display_nodes:view.display_nodes};
}

async function compare(page, comparison) {
  await page.evaluate(async () => {
    const T = await import("/npm/node_modules/three/build/three.module.js");
    const {GLTFLoader} = await import("/npm/node_modules/three/examples/jsm/loaders/GLTFLoader.js");
    const loader = new GLTFLoader();
    const renderer = new T.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
    renderer.setPixelRatio(1);
    renderer.setSize(640,420);
    const backdrop = new T.Color(0x202733);
    document.body.replaceChildren(renderer.domElement);
    document.body.style.margin = "0";
    renderer.domElement.id = "comparison";
    window.renderRegistration = async (cameraSpec, method) => {
      const url = `/registration-comparison/${method.file}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Unavailable comparison geometry ${response.status}`);
      const buffer = await response.arrayBuffer();
      const sha = [...new Uint8Array(await crypto.subtle.digest("SHA-256",buffer))]
        .map(x=>x.toString(16).padStart(2,"0")).join("");
      if (sha !== method.sha256) throw new Error("Comparison GLB digest mismatch");
      const gltf = await loader.parseAsync(buffer, "");
      const world = new T.Scene();
      world.background = backdrop;
      world.add(gltf.scene);
      world.add(new T.HemisphereLight(0xffffff, 0x5c5260, 2.2));
      const key = new T.DirectionalLight(0xffffff, 1.8);
      key.position.set(...cameraSpec.position);
      world.add(key);
      const w = cameraSpec.width_m/2,h = cameraSpec.height_m/2;
      const camera = new T.OrthographicCamera(-w,w,h,-h,.015,100);
      camera.position.set(...cameraSpec.position);
      camera.up.set(...cameraSpec.up);
      camera.lookAt(...cameraSpec.target);
      const mixer = new T.AnimationMixer(gltf.scene);
      const clip = gltf.animations[0];
      mixer.clipAction(clip).setLoop(T.LoopOnce, 1).play().clampWhenFinished = true;
      return j => {
        mixer.setTime(clip.tracks[0].times[j]);
        renderer.render(world,camera);
        let maxPosition = 0, maxProjection = 0, count = 0;
        for (const [name, target] of Object.entries(method.points)) {
          const obj = gltf.scene.getObjectByName(name);
          if (!obj?.isMesh || !obj.visible) throw new Error(`Missing mesh ${name}`);
          for (const [k, i] of target.indices.entries()) {
            const p = obj.getVertexPosition(i, new T.Vector3()).applyMatrix4(obj.matrixWorld);
            maxPosition = Math.max(maxPosition,p.distanceTo(new T.Vector3(...target.world_glb_m[j][k])));
            const uv = p.project(camera);
            maxProjection = Math.max(maxProjection, Math.abs((uv.x+1)/2-target.viewport_uv[j][k][0]),
              Math.abs((uv.y+1)/2-target.viewport_uv[j][k][1]));
            count++;
          }
        }
        return {maxPosition,maxProjection,count};
      };
    };
  });
  const summary = [];
  for (const [region, sample] of Object.entries(comparison.regions)) {
    for (const [key, method] of Object.entries(sample.methods)) {
      await page.evaluate(async ({camera,method}) => {window.drawPilot = await window.renderRegistration(camera,method);},
        {camera:sample.camera,method});
      for (const [j,index] of sample.frames.entries()) {
        const measured = await page.evaluate(i => window.drawPilot(i),j);
        assert.ok(measured.maxPosition < 1e-5, JSON.stringify({region,key,index,...measured}));
        assert.ok(measured.maxProjection < 1e-5, JSON.stringify({region,key,index,...measured}));
        summary.push({region,method:key,state_index:index,...measured});
        await page.locator("#comparison").screenshot({path:`${out}/browser/matched-${region}-${key}-${String(index).padStart(3,"0")}.png`});
      }
    }
  }
  return summary;
}

(async () => {
  const vars = JSON.parse(await fs.readFile(out+"/registration-selections.json"));
  const comparison = JSON.parse(await fs.readFile(out+"/blender/matched-final/comparison.json"));
  const browser = await chromium.launch({args:["--use-gl=angle","--use-angle=vulkan","--enable-features=Vulkan",
    "--disable-vulkan-surface","--no-sandbox"]});
  const checks = [], consoleLog = [];
  let measured = [];
  try {
    for (const mobile of [false,true]) {
      const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:920},
        isMobile:mobile,hasTouch:mobile});
      const page = await context.newPage();
      const outside = [], errors = [];
      page.on("console",msg => consoleLog.push({mobile,type:msg.type(),text:msg.text()}));
      page.on("pageerror",err => errors.push(err.message));
      page.on("request",req => {if (!req.url().startsWith(origin+"/") && !req.url().startsWith("blob:")) outside.push(req.url());});
      await page.goto(origin+"/?motion=whole");
      await page.waitForFunction(() => window.hmmViewer?.whole.status()?.nodeCount > 400);
      const backend = await page.evaluate(() => {
        const gl = document.querySelector("#view").getContext("webgl2");
        const debug = gl.getExtension("WEBGL_debug_renderer_info");
        return [gl.getParameter(debug.UNMASKED_RENDERER_WEBGL), gl.getParameter(gl.VERSION)];
      });
      assert.match(backend[0],/NVIDIA.*Vulkan/i);
      for (const [label,view] of Object.entries(vars.views)) {
        checks.push({mobile,label,backend,...await inspect(page,label,view,mobile)});
      }
      if (!mobile) measured = await compare(page,comparison);
      assert.deepEqual(outside, []);
      assert.deepEqual(errors, []);
      await context.close();
    }
    await fs.writeFile(out+"/browser/registration-browser.json",JSON.stringify({checks,measured},null,2));
    console.log(`PASS ${checks.length} viewer cases and ${measured.length} browser/Blender matched comparisons`);
  } finally {
    await fs.writeFile(out+"/logs/browser-console.json",JSON.stringify(consoleLog,null,2));
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
