import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { expect, test } from "vitest";
import { Box3, Object3D, Vector3 } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { bindRig } from "./rig";
import type { Rig } from "../types";

test("rendered meshes and pivots match independent Blender poses for all four motions", async () => {
  const rig: Rig = JSON.parse(readFileSync("public/models/rig.json", "utf8"));
  const reference = JSON.parse(
    readFileSync("public/models/reference-poses.json", "utf8"),
  );
  const bytes = readFileSync("public/models/drx.glb");
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    reference.model_sha256,
  );
  const { scene } = await new GLTFLoader().parseAsync(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    "",
  );
  const binding = bindRig(scene, rig);
  const meshes: Record<string, Object3D> = {};
  scene.traverse((node) => {
    if (node.userData.drxLandmark) meshes[node.userData.drxLandmark] = node;
  });
  expect(Object.keys(meshes)).toHaveLength(5);
  const box = scene.getObjectByName("axial_rail_sleeve")!;
  const slider = scene.getObjectByName("axial_slider")!;
  expect(box.parent).toBe(slider);
  const relativeBoxPose = box.matrix.clone();
  // The actual exported box must remain rigidly attached through every pose.
  for (const pose of reference.poses) {
    binding.apply(pose.pose);
    scene.updateMatrixWorld(true);
    expect(box.matrix.elements).toEqual(relativeBoxPose.elements);
    for (const [name, expected] of Object.entries(pose.landmarks)) {
      const node = scene.getObjectByName(name)!;
      const actual = new Vector3(
        ...(reference.probe_gltf as [number, number, number]),
      ).applyMatrix4(node.matrixWorld);
      expect(
        actual.distanceTo(
          new Vector3(...(expected as [number, number, number])),
        ),
        `${pose.name}: ${name}`,
      ).toBeLessThan(0.00001);
    }
    for (const [name, expected] of Object.entries(pose.mesh_landmarks) as [
      string,
      { local: [number, number, number]; world: [number, number, number] },
    ][]) {
      const actual = new Vector3(...expected.local).applyMatrix4(
        meshes[name].matrixWorld,
      );
      expect(
        actual.distanceTo(new Vector3(...expected.world)),
        `${pose.name}: visible ${name}`,
      ).toBeLessThan(0.00001);
    }
    const stationary = Object.values(meshes).map((node) =>
      node.matrixWorld.clone(),
    );
    // Repeated 20 Hz snapshots must not accumulate transforms or shake parts.
    for (let frame = 0; frame < 120; frame++) {
      binding.apply({ ...pose.pose });
      scene.updateMatrixWorld(true);
      Object.values(meshes).forEach((node, i) => {
        expect(node.matrixWorld.elements).toEqual(stationary[i].elements);
      });
    }
  }
  binding.restore();
  binding.apply({
    axial_inches: 0,
    horizontal_degrees: 0,
    lateral_degrees: 0,
    fit_inches: 0,
  });
  scene.updateMatrixWorld(true);
  const body = slider.children.find((node) => node !== box)!;
  const bodyCenter = new Box3().setFromObject(body).getCenter(new Vector3());
  const boxCenter = new Box3().setFromObject(box).getCenter(new Vector3());
  expect(
    Math.abs(bodyCenter.x - boxCenter.x),
    "box centered across fixture",
  ).toBeLessThan(0.001);
  expect(
    Math.abs(boxCenter.y - bodyCenter.y),
    "box vertically centered inside cage",
  ).toBeLessThan(0.005);
  binding.restore();
});
