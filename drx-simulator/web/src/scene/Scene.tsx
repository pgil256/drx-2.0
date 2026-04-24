import { Canvas } from '@react-three/fiber';
import { Environment, OrbitControls, Bounds } from '@react-three/drei';
import { Suspense } from 'react';
import { DeviceModel } from './DeviceModel';

export function Scene() {
  return (
    <Canvas camera={{ position: [2, 1.5, 2.5], fov: 45 }} shadows>
      <Suspense fallback={null}>
        <Environment preset="studio" />
        <directionalLight position={[3, 5, 3]} intensity={1.2} castShadow />
        <Bounds fit clip observe margin={1.2}>
          <DeviceModel />
        </Bounds>
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      </Suspense>
    </Canvas>
  );
}
