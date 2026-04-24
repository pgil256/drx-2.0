import { Canvas, useThree } from '@react-three/fiber';
import { Environment, OrbitControls } from '@react-three/drei';
import { Suspense, useEffect } from 'react';
import { DeviceModel } from './DeviceModel';
import { CAMERA_PRESETS } from './cameraPresets';
import { useAppStore } from '../store/useAppStore';

function CameraRig() {
  const { camera } = useThree();
  const presetId = useAppStore((s) => s.ui.cameraPreset);
  useEffect(() => {
    const p = CAMERA_PRESETS.find((x) => x.id === presetId) ?? CAMERA_PRESETS[0];
    camera.position.set(...p.position);
    camera.lookAt(...p.target);
  }, [presetId, camera]);
  return null;
}

export function Scene() {
  return (
    <Canvas camera={{ position: [2.2, 1.5, 2.5], fov: 45 }} shadows>
      <Suspense fallback={null}>
        <Environment preset="studio" />
        <directionalLight position={[3, 5, 3]} intensity={1.2} castShadow />
        <DeviceModel />
        <CameraRig />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      </Suspense>
    </Canvas>
  );
}
