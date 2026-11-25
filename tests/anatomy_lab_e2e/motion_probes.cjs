/** Inspect the small baked GLB in the actual browser and record unaltered whole-body playback. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const [base, clip, evidence] = process.argv.slice(2);

async function main() {
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=vulkan",
    "--enable-features=Vulkan", "--disable-vulkan-surface", "--no-sandbox"] });
  try {
    const context = await browser.newContext({ viewport: {width:1440, height:900},
      recordVideo: {dir: evidence, size: {width:960, height:600}} });
    const page = await context.newPage();
    await page.goto(base + "/?motion=whole");
    const video = page.video();
    await page.locator("#whole-controls").waitFor();
    await page.locator("#whole-play").click();
    await page.waitForFunction(() => !window.hmmViewer.whole.status().playing
      && window.hmmViewer.whole.status().frame.state_index === 110);
    await context.close();
    await video.saveAs(evidence + "/browser-capture.webm");
    await video.delete();
    const check = await browser.newPage();
    await check.goto(base + "/?motion=whole");
    await check.locator("#whole-controls").waitFor();
    await check.evaluate(() => window.hmmViewer.whole.seek(55));
    const bones = check.locator('#whole-layers input[value="SKELETON"]');
    await bones.uncheck();
    await check.locator("#view").screenshot({path: evidence + "/browser-muscles-only.png"});
    await bones.check();
    const canvas = await check.locator("#view").boundingBox();
    const firstCamera = await check.evaluate(() => window.hmmViewer.getScene().camera.position);
    await check.mouse.move(canvas.x + canvas.width * .73, canvas.y + canvas.height * .48);
    await check.mouse.down();
    await check.mouse.move(canvas.x + canvas.width * .24, canvas.y + canvas.height * .48, {steps: 12});
    await check.mouse.up();
    const otherCamera = await check.evaluate(() => window.hmmViewer.getScene().camera.position);
    assert.ok(firstCamera[2] * otherCamera[2] < 0, JSON.stringify({firstCamera,otherCamera}));
    await check.locator("#view").screenshot({path: evidence + "/browser-other-side.png"});
    await check.locator("#reset").click();
    await check.locator("#whole-static").click();
    await check.waitForFunction(() => window.hmmViewer.getScene().scene === "whole-anterior");
    await check.locator("#view").screenshot({path: evidence + "/browser-static-skin.png"});
    const report = [];
    for (const name of ["baked", "sharpened"]) {
      const data = await fs.readFile(`${clip}/${name}-probe.glb`);
      const expected = JSON.parse(await fs.readFile(`${clip}/${name}-probe.json`));
      const measurement = await check.evaluate(async ({ data, expected }) => {
        const THREE = await import("three");
        const {GLTFLoader} = await import("./npm/node_modules/three/examples/jsm/loaders/GLTFLoader.js");
        const blob = Uint8Array.from(atob(data), c => c.charCodeAt(0));
        const start = performance.now();
        const gltf = await new GLTFLoader().parseAsync(blob.buffer, "");
        const importMs = performance.now() - start;
        const renderer = new THREE.WebGLRenderer({preserveDrawingBuffer:true});
        renderer.setSize(480, 400);
        const world = new THREE.Scene();
        world.add(gltf.scene, new THREE.HemisphereLight(0xffffff, 0x444455, 3));
        const cam = new THREE.PerspectiveCamera(35, 1.2, .015, 30);
        cam.position.set(1.99,.86,1.24);
        cam.lookAt(1.21,.29,0);
        const mixer = new THREE.AnimationMixer(gltf.scene);
        mixer.clipAction(gltf.animations[0]).setLoop(THREE.LoopOnce,0).play();
        const mesh = gltf.scene.children[0];
        const points = [], drawMs = [];
        for (const time of expected.times_s) {
          mixer.setTime(time);
          world.updateMatrixWorld(true);
          const before = performance.now();
          renderer.render(world, cam);
          await new Promise(requestAnimationFrame);
          drawMs.push(performance.now() - before);
          points.push(expected.vertex_indices.map(i =>
            mesh.getVertexPosition(i,new THREE.Vector3()).applyMatrix4(mesh.matrixWorld).toArray()));
        }
        const gl = renderer.getContext();
        const rendererName = gl.getParameter(gl.getExtension("WEBGL_debug_renderer_info").UNMASKED_RENDERER_WEBGL);
        renderer.dispose();
        return {importMs, drawMs, points, rendererName, mesh:mesh.name, bytes:blob.byteLength};
      }, {data: data.toString("base64"), expected});
      const errors = measurement.points.flatMap((vertices, i) => vertices.map((point, j) =>
        Math.hypot(...point.map((v, k) => v - expected.world_glb_m[i][j][k]))));
      const max = Math.max(...errors);
      assert.ok(max < .0001, String(max));
      assert.match(measurement.rendererName, /NVIDIA.*Vulkan/);
      report.push({name, ...measurement, vertexIndices:expected.vertex_indices, timesS:expected.times_s,
        maxM:max, rmsM:Math.sqrt(errors.reduce((a,b) => a+b*b,0)/errors.length)});
    }
    await fs.writeFile(evidence + "/interchange-browser.json", JSON.stringify(report,null,2) + "\n");
    console.log(JSON.stringify(report.map(({points, ...v}) => v), null, 2));
  } finally {
    await browser.close();
  }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
