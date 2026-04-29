import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import type { Mesh, MeshStandardMaterial, Object3D } from 'three';
import { useAppStore } from '../store/useAppStore';

const STRAP_MESH_NAMES = new Set(['Bent leg:1', 'Bent leg 2:1']);
const LEG_NODE_NAMES = new Set([
  'Bent leg:1',
  'Bent leg 2:1',
  'Vertical leg 1:1',
  'Vertical leg 1:2',
  'Vertical leg 2:1',
  'Vertical leg 2:2',
]);
const PRESSURE_MAX_LBS = 80;
const GLOW_MAX_INTENSITY = 0.8;
const GLOW_COLOR = 0xff2a2a;
const PULSE_HZ = 1.5;
const PULSE_GLOW_AMPLITUDE = 1.2;

// Rest-pose calibration: the GLB authors the leg tilted up from horizontal.
// This offset makes horizontal.pos = -15 (the initial store value) render parallel to the ground.
const HORIZONTAL_REST_CALIBRATION_DEG = 15;

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

  const strapMatsRef = useRef<MeshStandardMaterial[]>([]);

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

    // The raw GLB authors the patient leg meshes as siblings of horizontal_pivot,
    // so they don't follow the actuators. Reparent them under axial_slider so they
    // tilt with horizontal, swing with lateral, and translate with axial.
    scene.updateMatrixWorld(true);
    const legs: Object3D[] = [];
    scene.traverse((obj) => {
      if (LEG_NODE_NAMES.has(obj.name)) legs.push(obj);
    });
    for (const leg of legs) {
      axialRef.current.attach(leg);
    }
    if (legs.length === 0) {
      console.warn('DeviceModel: no leg meshes found to reparent');
    }

    const mats: MeshStandardMaterial[] = [];
    scene.traverse((obj: Object3D) => {
      const mesh = obj as Mesh;
      if (!mesh.isMesh || !STRAP_MESH_NAMES.has(mesh.name)) return;
      const src = mesh.material as MeshStandardMaterial;
      const cloned = src.clone();
      cloned.emissive.setHex(GLOW_COLOR);
      cloned.emissiveIntensity = 0;
      mesh.material = cloned;
      mats.push(cloned);
    });
    strapMatsRef.current = mats;
    if (mats.length === 0) {
      console.warn('DeviceModel: no strap meshes matched for glow effect');
    }
  }, [scene]);

  useFrame((state) => {
    const d = useAppStore.getState().device;
    if (axialRef.current) {
      axialRef.current.position.z = axialBaseZRef.current + d.axial.pos * IN_TO_M;
    }
    if (lateralRef.current) {
      lateralRef.current.rotation.y = lateralBaseYRef.current + degToRad(d.lateral.pos);
    }
    if (horizontalRef.current) {
      horizontalRef.current.rotation.x =
        horizontalBaseXRef.current + degToRad(d.horizontal.pos + HORIZONTAL_REST_CALIBRATION_DEG);
    }

    const pressureGlow = (d.pressure.lbs / PRESSURE_MAX_LBS) * GLOW_MAX_INTENSITY;
    const pulseHighlight = d.pulsing
      ? (0.5 + 0.5 * Math.sin(state.clock.getElapsedTime() * 2 * Math.PI * PULSE_HZ)) *
        PULSE_GLOW_AMPLITUDE
      : 0;
    const glow = pressureGlow + pulseHighlight;
    for (const mat of strapMatsRef.current) {
      mat.emissiveIntensity = glow;
    }
  });

  return <primitive object={scene} />;
}

useGLTF.preload('/models/drx.glb');
