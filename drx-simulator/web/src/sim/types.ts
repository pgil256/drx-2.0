export type ActuatorState = {
  pos: number;
  target: number;
  moving: boolean;
};

export type PressureState = {
  lbs: number;
  target: number;
};

export type DeviceState = {
  axial: ActuatorState;
  horizontal: ActuatorState;
  lateral: ActuatorState;
  pressure: PressureState;
  pulsing: boolean;
  eStop: boolean;
};

export const INITIAL_DEVICE_STATE: DeviceState = {
  axial: { pos: 0, target: 0, moving: false },
  horizontal: { pos: -15, target: -15, moving: false },
  lateral: { pos: 0, target: 0, moving: false },
  pressure: { lbs: 0, target: 0 },
  pulsing: false,
  eStop: false,
};

export const LIMITS = {
  axial: { min: 0, max: 4 },
  horizontal: { min: -25, max: 5 },
  lateral: { min: -20, max: 20 },
  pressure: { min: 0, max: 80 },
} as const;

export const SPEEDS = {
  axial: 1.0,
  horizontal: 30,
  lateral: 30,
  pressure: 20,
} as const;
