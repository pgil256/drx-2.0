import { describe, it, expect } from 'vitest';
import { stepActuator } from './step';

describe('stepActuator', () => {
  it('moves toward target at the given speed', () => {
    const next = stepActuator({ pos: 0, target: 2, moving: true }, 1.0, 0.5);
    expect(next.pos).toBeCloseTo(0.5, 5);
    expect(next.moving).toBe(true);
  });

  it('clamps to target and clears moving flag when within step size', () => {
    const next = stepActuator({ pos: 1.9, target: 2, moving: true }, 1.0, 0.5);
    expect(next.pos).toBe(2);
    expect(next.moving).toBe(false);
  });

  it('moves backwards when target is less than position', () => {
    const next = stepActuator({ pos: 2, target: 0, moving: true }, 1.0, 0.5);
    expect(next.pos).toBeCloseTo(1.5, 5);
    expect(next.moving).toBe(true);
  });

  it('does nothing when not moving', () => {
    const next = stepActuator({ pos: 1, target: 2, moving: false }, 1.0, 0.5);
    expect(next.pos).toBe(1);
    expect(next.moving).toBe(false);
  });
});
