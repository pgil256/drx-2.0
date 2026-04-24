import type { ActuatorState } from './types';

export function stepActuator(
  state: ActuatorState,
  speedPerSec: number,
  dtSec: number,
): ActuatorState {
  if (!state.moving) return state;

  const delta = state.target - state.pos;
  const maxStep = speedPerSec * dtSec;

  if (Math.abs(delta) <= maxStep) {
    return { pos: state.target, target: state.target, moving: false };
  }

  const direction = Math.sign(delta);
  return { ...state, pos: state.pos + direction * maxStep };
}
