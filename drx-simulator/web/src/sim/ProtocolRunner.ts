import { useAppStore, type ProtocolId, type ProtocolPhase } from '../store/useAppStore';
import type { SimulatedDevice } from './SimulatedDevice';

const PRESSURE_TOLERANCE = 2;
const ANGLE_TOLERANCE = 0.5;
const OSCILLATION_HALF_PERIOD_SEC = 8;
const COOLING_SEC = 1.5;

export class ProtocolRunner {
  private device: Pick<SimulatedDevice, 'send'>;
  private oscDir: 'left' | 'right' = 'left';
  private nextSwitchSec = 0;
  private coolingStartedAtSec: number | null = null;

  constructor(device: Pick<SimulatedDevice, 'send'>) {
    this.device = device;
  }

  start(id: ProtocolId): void {
    const s = useAppStore.getState();
    if (s.device.eStop || s.session.runningProtocol != null) return;

    this.oscDir = 'left';
    this.nextSwitchSec = OSCILLATION_HALF_PERIOD_SEC;
    this.coolingStartedAtSec = null;

    s.setSession({
      runningProtocol: id,
      phase: 'ramping',
      elapsedSec: 0,
      progressPct: 0,
    });

    this.device.send(`P${Math.round(s.session.maxPressure)}`);
  }

  stop(): void {
    const s = useAppStore.getState();
    if (s.session.runningProtocol == null) return;
    this.device.send('JS');
    this.device.send('K 0');
    this.device.send('P0');
    s.setSession({
      runningProtocol: null,
      phase: 'idle',
      elapsedSec: 0,
      progressPct: 0,
    });
    this.coolingStartedAtSec = null;
  }

  tick(dtSec: number): void {
    const s = useAppStore.getState();
    const id = s.session.runningProtocol;
    if (id == null) return;

    if (s.device.eStop) {
      this.stop();
      return;
    }

    const elapsedSec = s.session.elapsedSec + dtSec;
    const durationSec = s.session.durationSec;
    const progressPct = Math.min(100, (elapsedSec / durationSec) * 100);

    let phase: ProtocolPhase = s.session.phase;
    phase = this.advancePhase(id, phase, elapsedSec, s);

    s.setSession({ elapsedSec, progressPct, phase });

    if (phase === 'done') {
      s.setSession({ runningProtocol: null, phase: 'idle', elapsedSec: 0, progressPct: 0 });
      this.coolingStartedAtSec = null;
    }
  }

  private advancePhase(
    id: ProtocolId,
    phase: ProtocolPhase,
    elapsedSec: number,
    s: ReturnType<typeof useAppStore.getState>,
  ): ProtocolPhase {
    const atPressure =
      Math.abs(s.device.pressure.lbs - s.session.maxPressure) <= PRESSURE_TOLERANCE;
    const durationSec = s.session.durationSec;
    const durationElapsed = elapsedSec >= durationSec;

    switch (phase) {
      case 'ramping':
        if (!atPressure) return 'ramping';
        if (id === 1) return this.enterHoldOrPulse(s);
        return this.beginPositioning(id, s);

      case 'positioning': {
        const targetAngle = this.angleFor(id, s);
        const atAngle = Math.abs(s.device.lateral.pos - targetAngle) <= ANGLE_TOLERANCE;
        if (!atAngle) return 'positioning';
        if (id === 4) return this.beginOscillating(s);
        return this.enterHoldOrPulse(s);
      }

      case 'holding':
      case 'pulsing':
        if (durationElapsed) return this.beginCooling(elapsedSec);
        return phase;

      case 'oscillating':
        if (durationElapsed) {
          if (s.session.usePulse) this.device.send('JS');
          return this.beginCooling(elapsedSec);
        }
        if (elapsedSec >= this.nextSwitchSec) {
          this.oscDir = this.oscDir === 'left' ? 'right' : 'left';
          this.device.send(`K ${Math.round(this.oscAngle(s))}`);
          this.nextSwitchSec += OSCILLATION_HALF_PERIOD_SEC;
        }
        return 'oscillating';

      case 'cooling': {
        const startedAt = this.coolingStartedAtSec ?? elapsedSec;
        if (elapsedSec - startedAt >= COOLING_SEC) return 'done';
        return 'cooling';
      }

      default:
        return phase;
    }
  }

  private beginPositioning(
    id: ProtocolId,
    s: ReturnType<typeof useAppStore.getState>,
  ): ProtocolPhase {
    this.device.send(`K ${Math.round(this.angleFor(id, s))}`);
    return 'positioning';
  }

  private beginOscillating(s: ReturnType<typeof useAppStore.getState>): ProtocolPhase {
    if (s.session.usePulse) this.device.send('J');
    this.nextSwitchSec = s.session.elapsedSec + OSCILLATION_HALF_PERIOD_SEC;
    return 'oscillating';
  }

  private enterHoldOrPulse(s: ReturnType<typeof useAppStore.getState>): ProtocolPhase {
    if (s.session.usePulse) {
      this.device.send('J');
      return 'pulsing';
    }
    return 'holding';
  }

  private beginCooling(elapsedSec: number): ProtocolPhase {
    this.device.send('JS');
    this.device.send('K 0');
    this.device.send('P0');
    this.coolingStartedAtSec = elapsedSec;
    return 'cooling';
  }

  private angleFor(id: ProtocolId, s: ReturnType<typeof useAppStore.getState>): number {
    if (id === 2) return -Math.abs(s.session.maxLeft);
    if (id === 3) return Math.abs(s.session.maxRight);
    if (id === 4) return this.oscAngle(s);
    return 0;
  }

  private oscAngle(s: ReturnType<typeof useAppStore.getState>): number {
    return this.oscDir === 'left'
      ? -Math.abs(s.session.maxLeft)
      : Math.abs(s.session.maxRight);
  }
}
