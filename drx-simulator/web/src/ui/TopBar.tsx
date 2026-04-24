import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store/useAppStore';
import { simDevice } from '@/sim/useSimTick';

export function TopBar() {
  const eStop = useAppStore((s) => s.device.eStop);

  return (
    <div className="absolute top-0 left-0 right-0 h-14 flex items-center justify-between px-6 bg-black/40 backdrop-blur-md border-b border-white/10 pointer-events-auto">
      <div className="text-white font-medium tracking-wide">DRX Simulator</div>
      {eStop ? (
        <Button variant="destructive" onClick={() => simDevice.resetEStop()}>
          Reset E-Stop
        </Button>
      ) : (
        <Button variant="destructive" onClick={() => simDevice.send('X')}>
          E-STOP
        </Button>
      )}
    </div>
  );
}
