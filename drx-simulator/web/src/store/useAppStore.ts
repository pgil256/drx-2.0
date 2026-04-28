import { create } from 'zustand';
import { INITIAL_DEVICE_STATE, type DeviceState } from '../sim/types';

export type Page = 'home' | 'login' | 'setup' | 'protocols' | 'help';
export type SetupTab = 'axial' | 'horizontal' | 'lateral';
export type ProtocolId = 1 | 2 | 3 | 4;
export type ProtocolPhase =
  | 'idle'
  | 'ramping'
  | 'positioning'
  | 'holding'
  | 'pulsing'
  | 'oscillating'
  | 'cooling'
  | 'done';

type SessionState = {
  runningProtocol: ProtocolId | null;
  phase: ProtocolPhase;
  progressPct: number;
  elapsedSec: number;
  durationSec: number;
  maxPressure: number;
  maxLeft: number;
  maxRight: number;
  usePulse: boolean;
};

type UiState = {
  page: Page;
  setupTab: SetupTab;
  videoOpen: boolean;
  cameraPreset: 'three-quarter' | 'side' | 'overhead';
};

type AppState = {
  device: DeviceState;
  session: SessionState;
  ui: UiState;

  setDevice: (patch: Partial<DeviceState>) => void;
  setAxialTarget: (v: number) => void;
  setHorizontalTarget: (v: number) => void;
  setLateralTarget: (v: number) => void;
  setPressureTarget: (v: number) => void;
  setPulsing: (v: boolean) => void;
  setEStop: (v: boolean) => void;

  setSession: (patch: Partial<SessionState>) => void;
  setUi: (patch: Partial<UiState>) => void;
};

export const useAppStore = create<AppState>((set) => ({
  device: INITIAL_DEVICE_STATE,
  session: {
    runningProtocol: null,
    phase: 'idle',
    progressPct: 0,
    elapsedSec: 0,
    durationSec: 30,
    maxPressure: 40,
    maxLeft: 10,
    maxRight: 10,
    usePulse: false,
  },
  ui: {
    page: 'home',
    setupTab: 'axial',
    videoOpen: false,
    cameraPreset: 'three-quarter',
  },

  setDevice: (patch) => set((s) => ({ device: { ...s.device, ...patch } })),
  setAxialTarget: (v) =>
    set((s) => ({
      device: { ...s.device, axial: { ...s.device.axial, target: v, moving: true } },
    })),
  setHorizontalTarget: (v) =>
    set((s) => ({
      device: { ...s.device, horizontal: { ...s.device.horizontal, target: v, moving: true } },
    })),
  setLateralTarget: (v) =>
    set((s) => ({
      device: { ...s.device, lateral: { ...s.device.lateral, target: v, moving: true } },
    })),
  setPressureTarget: (v) =>
    set((s) => ({
      device: { ...s.device, pressure: { ...s.device.pressure, target: v } },
    })),
  setPulsing: (v) => set((s) => ({ device: { ...s.device, pulsing: v } })),
  setEStop: (v) => set((s) => ({ device: { ...s.device, eStop: v } })),

  setSession: (patch) => set((s) => ({ session: { ...s.session, ...patch } })),
  setUi: (patch) => set((s) => ({ ui: { ...s.ui, ...patch } })),
}));
