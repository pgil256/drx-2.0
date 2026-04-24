import { useAppStore } from '../store/useAppStore';
import { parseCommand } from './parseCommand';
import { stepActuator } from './step';
import { LIMITS, SPEEDS } from './types';

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

export class SimulatedDevice {
  send(raw: string): void {
    const parsed = parseCommand(raw);
    if (!parsed) return;

    const s = useAppStore.getState();
    if (s.device.eStop && parsed.kind !== 'eStop') return;

    switch (parsed.kind) {
      case 'axial':
        s.setAxialTarget(clamp(parsed.value, LIMITS.axial.min, LIMITS.axial.max));
        break;
      case 'horizontal':
        s.setHorizontalTarget(clamp(parsed.value, LIMITS.horizontal.min, LIMITS.horizontal.max));
        break;
      case 'lateral':
        s.setLateralTarget(clamp(parsed.value, LIMITS.lateral.min, LIMITS.lateral.max));
        break;
      case 'pressure':
        s.setPressureTarget(clamp(parsed.value, LIMITS.pressure.min, LIMITS.pressure.max));
        break;
      case 'pulseStart':
        s.setPulsing(true);
        break;
      case 'pulseStop':
        s.setPulsing(false);
        break;
      case 'eStop':
        s.setEStop(true);
        s.setPressureTarget(0);
        useAppStore.setState((prev) => ({
          device: {
            ...prev.device,
            axial: { ...prev.device.axial, moving: false },
            horizontal: { ...prev.device.horizontal, moving: false },
            lateral: { ...prev.device.lateral, moving: false },
          },
        }));
        break;
      case 'keepalive':
        break;
    }
  }

  tick(dtSec: number): void {
    const { device } = useAppStore.getState();
    if (device.eStop) return;

    const axial = stepActuator(device.axial, SPEEDS.axial, dtSec);
    const horizontal = stepActuator(device.horizontal, SPEEDS.horizontal, dtSec);
    const lateral = stepActuator(device.lateral, SPEEDS.lateral, dtSec);

    const pDelta = device.pressure.target - device.pressure.lbs;
    const pMax = SPEEDS.pressure * dtSec;
    const pressureLbs =
      Math.abs(pDelta) <= pMax
        ? device.pressure.target
        : device.pressure.lbs + Math.sign(pDelta) * pMax;

    useAppStore.setState({
      device: {
        ...device,
        axial,
        horizontal,
        lateral,
        pressure: { ...device.pressure, lbs: pressureLbs },
      },
    });
  }

  resetEStop(): void {
    useAppStore.getState().setEStop(false);
  }
}
