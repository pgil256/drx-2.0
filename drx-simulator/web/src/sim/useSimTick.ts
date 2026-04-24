import { useEffect, useRef } from 'react';
import { SimulatedDevice } from './SimulatedDevice';

export const simDevice = new SimulatedDevice();

export function useSimTick() {
  const lastTimeRef = useRef<number | null>(null);

  useEffect(() => {
    let rafId = 0;
    const tick = (now: number) => {
      if (lastTimeRef.current == null) lastTimeRef.current = now;
      const dt = (now - lastTimeRef.current) / 1000;
      lastTimeRef.current = now;
      simDevice.tick(Math.min(dt, 0.1));
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);
}
