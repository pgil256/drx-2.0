import { useEffect, useRef } from 'react';
import { ProtocolRunner } from './ProtocolRunner';
import { SimulatedDevice } from './SimulatedDevice';

export const simDevice = new SimulatedDevice();
export const protocolRunner = new ProtocolRunner(simDevice);

export function useSimTick() {
  const lastTimeRef = useRef<number | null>(null);

  useEffect(() => {
    let rafId = 0;
    const tick = (now: number) => {
      if (lastTimeRef.current == null) lastTimeRef.current = now;
      const dt = Math.min((now - lastTimeRef.current) / 1000, 0.1);
      lastTimeRef.current = now;
      simDevice.tick(dt);
      protocolRunner.tick(dt);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);
}
