import { Suspense, useEffect, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { Vector3 } from "three";
import type { Rig, Snapshot } from "../types";
import { bindRig } from "./rig";

function Device({ snapshot, rig }: { snapshot: Snapshot | null; rig: Rig }) {
  const { scene } = useGLTF("/models/drx.glb");
  const binding = useRef<ReturnType<typeof bindRig> | null>(null);
  const latest = useRef(snapshot);
  latest.current = snapshot;
  useEffect(() => {
    binding.current = bindRig(scene, rig);
    return () => binding.current?.restore();
  }, [rig, scene]);
  useFrame(() => {
    const pose = latest.current?.pose;
    if (!pose) return;
    binding.current?.apply(pose);
  });
  return <primitive object={scene} />;
}

function Camera({ preset }: { preset: string }) {
  const { camera, controls } = useThree();
  useEffect(() => {
    const target = new Vector3(0.25, 0.55, -0.04);
    const locations: Record<string, [number, number, number]> = {
      "3/4": [2.45, 1.5, 2.46],
      Side: [3.75, 0.8, -0.04],
      Top: [0.25, 4, -0.03],
    };
    camera.up.set(0, 1, 0);
    camera.position.set(...locations[preset]);
    camera.lookAt(target);
    const orbit = controls as unknown as {
      target: Vector3;
      update: () => void;
    } | null;
    if (orbit) {
      orbit.target.copy(target);
      orbit.update();
    }
  }, [preset, camera, controls]);
  return null;
}

export function DeviceScene({
  snapshot,
  rig,
  preset,
}: {
  snapshot: Snapshot | null;
  rig: Rig;
  preset: string;
}) {
  return (
    <Canvas
      shadows
      camera={{ position: [2.45, 1.5, 2.46], fov: 40, near: 0.02, far: 50 }}
    >
      <color attach="background" args={["#edf0ef"]} />
      <ambientLight intensity={1.4} />
      <directionalLight position={[3, 5, 3]} intensity={2.5} castShadow />
      <directionalLight position={[-3, 4, -2]} intensity={1.2} />
      <Suspense fallback={null}>
        {/* Camera presets and OrbitControls share one target. Animated Bounds
            also wrote the camera on feed updates, causing visible shaking. */}
        <Device snapshot={snapshot} rig={rig} />
        <Grid
          position={[0, -0.015, 0]}
          args={[8, 8]}
          cellSize={0.25}
          cellThickness={0.45}
          cellColor="#bbc5c1"
          sectionSize={1}
          sectionColor="#a8b6b0"
          fadeDistance={8}
        />
      </Suspense>
      <OrbitControls
        makeDefault
        enableDamping
        minDistance={0.5}
        maxDistance={7}
      />
      <Camera preset={preset} />
    </Canvas>
  );
}
