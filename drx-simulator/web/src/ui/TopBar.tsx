import { Button } from '@/components/ui/button';
import { CAMERA_PRESETS } from '@/scene/cameraPresets';
import { useAppStore } from '@/store/useAppStore';
import { simDevice } from '@/sim/useSimTick';

export function TopBar() {
  const eStop = useAppStore((s) => s.device.eStop);
  const preset = useAppStore((s) => s.ui.cameraPreset);
  const setUi = useAppStore((s) => s.setUi);

  return (
    <div className="h-14 shrink-0 flex items-center justify-between px-6 bg-black/40 backdrop-blur-md border-b border-white/10">
      <div className="text-white font-medium tracking-wide">DRX Simulator</div>
      <div className="flex items-center gap-1 rounded-md bg-white/5 p-1 border border-white/10">
        {CAMERA_PRESETS.map((p) => (
          <Button
            key={p.id}
            size="sm"
            variant={preset === p.id ? 'default' : 'ghost'}
            onClick={() => setUi({ cameraPreset: p.id })}
          >
            {p.label}
          </Button>
        ))}
      </div>
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
