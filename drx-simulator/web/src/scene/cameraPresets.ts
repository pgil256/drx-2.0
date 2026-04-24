import type { Vector3Tuple } from 'three';

export type CameraPreset = {
  id: 'overhead' | 'side' | 'three-quarter';
  label: string;
  position: Vector3Tuple;
  target: Vector3Tuple;
};

export const CAMERA_PRESETS: CameraPreset[] = [
  { id: 'three-quarter', label: '3/4 View', position: [2.2, 1.5, 2.5], target: [0, 0.6, 0] },
  { id: 'side',          label: 'Side',     position: [3.5, 0.8, 0],   target: [0, 0.6, 0] },
  { id: 'overhead',      label: 'Overhead', position: [0, 4, 0.01],    target: [0, 0, 0] },
];
