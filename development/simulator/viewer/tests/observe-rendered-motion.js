/* Browser acceptance probe, evaluated with agent-browser eval --stdin.
 * Run while playing the smoke-test recording. It observes the real renderer;
 * it never sets actuator positions, changes the camera, or bypasses the GUI.
 * React's pinned Canvas implementation is inspected only in this test helper.
 */
(async () => {
  const canvas = document.querySelector("canvas");
  if (!canvas) throw new Error("Open a loaded simulator viewer first");
  let fiber = canvas[Object.keys(canvas).find(key => key.startsWith("__reactFiber"))];
  let root;
  while (fiber && !root) {
    let hook = fiber.memoizedState;
    for (let i = 0; hook && i < 80; i++, hook = hook.next) {
      const ref = hook.memoizedState?.current;
      if (ref?.render && ref?.configure) root = ref;
    }
    fiber = fiber.return;
  }
  if (!root) throw new Error("Could not inspect the pinned Canvas renderer");
  let store;
  const original = root.render;
  root.render = function (...args) {
    store = original.apply(this, args);
    root.render = original;
    return store;
  };
  const deadline = Date.now() + 3000;
  while (!store && Date.now() < deadline) await new Promise(r => setTimeout(r, 20));
  root.render = original;
  if (!store) throw new Error("Wait for live feed or playback updates before observing");
  const samples = [];
  function sample() {
    const {scene, camera} = store.getState();
    const vertices = {};
    scene.traverse(node => {
      const label = node.userData.drxLandmark;
      if (!label) return;
      let mesh;
      node.traverse(child => { if (!mesh && child.isMesh) mesh = child; });
      if (!mesh) throw new Error(`No visible mesh for ${label}`);
      const point = mesh.position.clone().fromBufferAttribute(mesh.geometry.attributes.position, 0);
      mesh.localToWorld(point);
      vertices[label] = point.toArray();
    });
    samples.push({
      camera: [...camera.position.toArray(), ...camera.quaternion.toArray()],
      fit: scene.getObjectByName("fit_slider").position.z,
      vertices,
    });
  }
  const timer = setInterval(sample, 16);
  const timeout = setTimeout(() => clearInterval(timer), 35000);
  window.drxRenderProbe = {
    finish() {
      clearInterval(timer);
      clearTimeout(timeout);
      if (samples.length < 120) throw new Error("Capture at least 120 frames");
      const spread = values => Math.max(...values) - Math.min(...values);
      const cameraVariation = Math.max(...samples[0].camera.map((_, i) =>
        spread(samples.map(s => s.camera[i]))));
      const vertexTravel = Object.fromEntries(Object.keys(samples[0].vertices).map(label => {
        const extents = [0, 1, 2].map(i => spread(samples.map(s => s.vertices[label][i])));
        return [label, Math.hypot(...extents)];
      }));
      const result = {frames: samples.length, cameraVariation,
        fitTravelMeters: spread(samples.map(s => s.fit)), vertexTravel};
      if (cameraVariation > 1e-9) throw new Error(`Camera is shaking: ${JSON.stringify(result)}`);
      if (vertexTravel["fixed-chair"] > 1e-9) throw new Error("Chair moved with the actuators");
      if (result.fitTravelMeters < 0.07) throw new Error("Did not observe the fast FIT stroke");
      for (const label of ["front-support", "leg-tray", "traction-carriage", "fixture-box"]) {
        if (vertexTravel[label] < 0.01) throw new Error(`No visible movement: ${label}`);
      }
      return {passed: true, ...result};
    },
  };
  return "Observing rendered meshes and camera for up to 35 seconds";
})()
