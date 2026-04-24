import { useGLTF } from '@react-three/drei';

export function DeviceModel() {
  const { scene } = useGLTF('/models/drx.glb');
  return <primitive object={scene} />;
}

useGLTF.preload('/models/drx.glb');
