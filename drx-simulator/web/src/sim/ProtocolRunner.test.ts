import { describe, it, expect, beforeEach } from 'vitest';
import { ProtocolRunner } from './ProtocolRunner';
import { useAppStore } from '../store/useAppStore';
import { INITIAL_DEVICE_STATE } from './types';

function freshStore(overrides: { maxPressure?: number; durationSec?: number; usePulse?: boolean; maxLeft?: number; maxRight?: number } = {}) {
  useAppStore.setState({
    device: structuredClone(INITIAL_DEVICE_STATE),
    session: {
      runningProtocol: null,
      phase: 'idle',
      progressPct: 0,
      elapsedSec: 0,
      durationSec: overrides.durationSec ?? 30,
      maxPressure: overrides.maxPressure ?? 40,
      maxLeft: overrides.maxLeft ?? 10,
      maxRight: overrides.maxRight ?? 10,
      usePulse: overrides.usePulse ?? false,
    },
  });
}

class MockDevice {
  sent: string[] = [];
  send(cmd: string) {
    this.sent.push(cmd);
  }
}

function pinPressureToTarget() {
  const s = useAppStore.getState();
  useAppStore.setState({
    device: {
      ...s.device,
      pressure: { ...s.device.pressure, lbs: s.session.maxPressure },
    },
  });
}

function pinLateralTo(angle: number) {
  const s = useAppStore.getState();
  useAppStore.setState({
    device: {
      ...s.device,
      lateral: { ...s.device.lateral, pos: angle },
    },
  });
}

describe('ProtocolRunner', () => {
  beforeEach(() => {
    freshStore();
  });

  it('start(1) marks running and sends initial pressure command', () => {
    const dev = new MockDevice();
    new ProtocolRunner(dev).start(1);

    expect(useAppStore.getState().session.runningProtocol).toBe(1);
    expect(useAppStore.getState().session.phase).toBe('ramping');
    expect(dev.sent).toEqual(['P40']);
  });

  it('protocol 1 advances ramping → holding once pressure reaches target', () => {
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(1);

    runner.tick(1);
    expect(useAppStore.getState().session.phase).toBe('ramping');

    pinPressureToTarget();
    runner.tick(1);
    expect(useAppStore.getState().session.phase).toBe('holding');
  });

  it('protocol 1 with usePulse enters pulsing and issues J command', () => {
    freshStore({ usePulse: true });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(1);
    pinPressureToTarget();
    runner.tick(1);

    expect(useAppStore.getState().session.phase).toBe('pulsing');
    expect(dev.sent).toContain('J');
  });

  it('protocol 2 issues lateral command after pressure ramp', () => {
    freshStore({ maxLeft: 12 });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(2);
    pinPressureToTarget();
    runner.tick(1);

    expect(useAppStore.getState().session.phase).toBe('positioning');
    expect(dev.sent).toContain('K -12');
  });

  it('protocol 3 sends positive lateral angle', () => {
    freshStore({ maxRight: 8 });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(3);
    pinPressureToTarget();
    runner.tick(1);

    expect(dev.sent).toContain('K 8');
  });

  it('protocol 2 transitions to holding once lateral target is reached', () => {
    freshStore({ maxLeft: 12 });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(2);
    pinPressureToTarget();
    runner.tick(1);
    pinLateralTo(-12);
    runner.tick(1);

    expect(useAppStore.getState().session.phase).toBe('holding');
  });

  it('protocol 4 oscillates: switches direction after half-period', () => {
    freshStore({ maxLeft: 10, maxRight: 10, durationSec: 60 });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(4);

    pinPressureToTarget();
    runner.tick(1);
    expect(useAppStore.getState().session.phase).toBe('positioning');

    pinLateralTo(-10);
    runner.tick(1);
    expect(useAppStore.getState().session.phase).toBe('oscillating');

    const sentBefore = dev.sent.length;
    runner.tick(10);
    const newCmds = dev.sent.slice(sentBefore);
    expect(newCmds).toContain('K 10');
  });

  it('completes after duration: cools down then returns to idle', () => {
    freshStore({ durationSec: 5 });
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(1);
    pinPressureToTarget();
    runner.tick(1);

    runner.tick(5);
    expect(useAppStore.getState().session.phase).toBe('cooling');
    expect(dev.sent).toContain('P0');
    expect(dev.sent).toContain('K 0');

    runner.tick(2);
    expect(useAppStore.getState().session.runningProtocol).toBe(null);
    expect(useAppStore.getState().session.phase).toBe('idle');
  });

  it('stop() recenters device and clears running state immediately', () => {
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(2);
    runner.stop();

    expect(useAppStore.getState().session.runningProtocol).toBe(null);
    expect(useAppStore.getState().session.phase).toBe('idle');
    expect(dev.sent).toEqual(expect.arrayContaining(['JS', 'K 0', 'P0']));
  });

  it('eStop during run halts the protocol', () => {
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(1);
    useAppStore.setState((s) => ({ device: { ...s.device, eStop: true } }));

    runner.tick(1);
    expect(useAppStore.getState().session.runningProtocol).toBe(null);
  });

  it('start is a no-op while another protocol is running', () => {
    const dev = new MockDevice();
    const runner = new ProtocolRunner(dev);
    runner.start(1);
    const sentBefore = dev.sent.length;
    runner.start(2);
    expect(useAppStore.getState().session.runningProtocol).toBe(1);
    expect(dev.sent.length).toBe(sentBefore);
  });
});
