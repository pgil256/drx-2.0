import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import type { Object3D } from 'three';
import { useAppStore } from '../store/useAppStore';

const IN_TO_M = 0.0254;

function degToRad(deg: number) {
  return (deg * Math.PI) / 180;
}

export function DeviceModel() {
  const { scene } = useGLTF('/models/drx.glb');

  const axialRef = useRef<Object3D | null>(null);
  const lateralRef = useRef<Object3D | null>(null);
  const horizontalRef = useRef<Object3D | null>(null);

  const axialBaseZRef = useRef(0);
  const lateralBaseYRef = useRef(0);
  const horizontalBaseXRef = useRef(0);

  useEffect(() => {
    axialRef.current = scene.getObjectByName('axial_slider') ?? null;
    lateralRef.current = scene.getObjectByName('lateral_pivot') ?? null;
    horizontalRef.current = scene.getObjectByName('horizontal_pivot') ?? null;

    if (!axialRef.current || !lateralRef.current || !horizontalRef.current) {
      console.warn(
        'DeviceModel: pivot groups not found. Expected axial_slider, lateral_pivot, horizontal_pivot',
      );
      return;
    }

    axialBaseZRef.current = axialRef.current.position.z;
    lateralBaseYRef.current = lateralRef.current.rotation.y;
    horizontalBaseXRef.current = horizontalRef.current.rotation.x;
  }, [scene]);

  useFrame(() => {
    const d = useAppStore.getState().device;
    if (axialRef.current) {
      axialRef.current.position.z = axialBaseZRef.current + d.axial.pos * IN_TO_M;
    }
    if (lateralRef.current) {
      lateralRef.current.rotation.y = lateralBaseYRef.current + degToRad(d.lateral.pos);
    }
    if (horizontalRef.current) {
      horizontalRef.current.rotation.x = horizontalBaseXRef.current + degToRad(d.horizontal.pos);
    }
  });

  return <primitive object={scene} />;
}

useGLTF.preload('/models/drx.glb');
