import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import { LIMITS } from '@/sim/types';
import { protocolRunner } from '@/sim/useSimTick';
import { cn } from '@/lib/utils';
import { useAppStore, type ProtocolId } from '@/store/useAppStore';
import { PageShell } from './PageShell';

type ProtocolDef = {
  id: ProtocolId;
  name: string;
  blurb: string;
  needsLeft: boolean;
  needsRight: boolean;
};

const PROTOCOLS: ProtocolDef[] = [
  { id: 1, name: 'Axial', blurb: 'Pressure ramp + hold.', needsLeft: false, needsRight: false },
  { id: 2, name: 'Left Lateral', blurb: 'Ramp, then tilt left.', needsLeft: true, needsRight: false },
  { id: 3, name: 'Right Lateral', blurb: 'Ramp, then tilt right.', needsLeft: false, needsRight: true },
  { id: 4, name: 'Oscillating', blurb: 'Ramp, then swing L↔R.', needsLeft: true, needsRight: true },
];

const PHASE_LABEL: Record<string, string> = {
  idle: 'Idle',
  ramping: 'Ramping pressure',
  positioning: 'Positioning',
  holding: 'Holding',
  pulsing: 'Pulsing',
  oscillating: 'Oscillating',
  cooling: 'Cooling down',
  done: 'Complete',
};

export function ProtocolsPage() {
  const session = useAppStore((s) => s.session);
  const device = useAppStore((s) => s.device);
  const setSession = useAppStore((s) => s.setSession);

  const [selected, setSelected] = useState<ProtocolId>(session.runningProtocol ?? 1);
  const isRunning = session.runningProtocol != null;
  const activeId = session.runningProtocol ?? selected;
  const def = PROTOCOLS.find((p) => p.id === activeId)!;

  return (
    <PageShell title="Protocols">
      <div className="space-y-5">
        {isRunning && (
          <div className="rounded-md border border-white/15 bg-white/5 p-4 space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <div>
                <div className="text-xs uppercase tracking-wide text-white/50">Running</div>
                <div className="text-lg font-medium">
                  Protocol {session.runningProtocol} — {def.name}
                </div>
              </div>
              <div className="text-sm text-white/70">{PHASE_LABEL[session.phase]}</div>
            </div>
            <div className="h-2 rounded-full bg-white/10 overflow-hidden">
              <div
                className="h-full bg-emerald-400/80 transition-[width] duration-200"
                style={{ width: `${session.progressPct}%` }}
              />
            </div>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <Stat label="Elapsed" value={`${Math.floor(session.elapsedSec)}s / ${session.durationSec}s`} />
              <Stat
                label="Pressure"
                value={`${device.pressure.lbs.toFixed(0)} / ${session.maxPressure} lbs`}
              />
              <Stat label="Lateral" value={`${device.lateral.pos.toFixed(1)}°`} />
            </div>
            <Button variant="destructive" onClick={() => protocolRunner.stop()}>
              Stop Protocol
            </Button>
          </div>
        )}

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {PROTOCOLS.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={isRunning}
              onClick={() => setSelected(p.id)}
              className={cn(
                'text-left transition disabled:opacity-50 disabled:cursor-not-allowed',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60 rounded-xl',
              )}
            >
              <Card
                size="sm"
                className={cn(
                  'h-full',
                  activeId === p.id
                    ? 'ring-2 ring-emerald-400/80 bg-emerald-400/5'
                    : 'hover:bg-white/5',
                )}
              >
                <CardContent className="space-y-1">
                  <div className="text-xs text-white/50">Protocol {p.id}</div>
                  <CardTitle>{p.name}</CardTitle>
                  <CardDescription>{p.blurb}</CardDescription>
                </CardContent>
              </Card>
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
          <SettingSlider
            label="Max Pressure"
            value={session.maxPressure}
            unit="lbs"
            min={0}
            max={LIMITS.pressure.max}
            step={1}
            disabled={isRunning}
            onChange={(v) => setSession({ maxPressure: v })}
          />
          <SettingSlider
            label="Duration"
            value={session.durationSec}
            unit="s"
            min={5}
            max={120}
            step={5}
            disabled={isRunning}
            onChange={(v) => setSession({ durationSec: v })}
          />
          {def.needsLeft && (
            <SettingSlider
              label="Max Left Angle"
              value={session.maxLeft}
              unit="°"
              min={0}
              max={LIMITS.lateral.max}
              step={1}
              disabled={isRunning}
              onChange={(v) => setSession({ maxLeft: v })}
            />
          )}
          {def.needsRight && (
            <SettingSlider
              label="Max Right Angle"
              value={session.maxRight}
              unit="°"
              min={0}
              max={LIMITS.lateral.max}
              step={1}
              disabled={isRunning}
              onChange={(v) => setSession({ maxRight: v })}
            />
          )}
        </div>

        <div className="flex items-center justify-between gap-3">
          <Button
            variant={session.usePulse ? 'default' : 'outline'}
            onClick={() => setSession({ usePulse: !session.usePulse })}
          >
            Pulse: {session.usePulse ? 'On' : 'Off'}
          </Button>
          {!isRunning && (
            <Button onClick={() => protocolRunner.start(selected)} disabled={device.eStop}>
              Start Protocol {selected}
            </Button>
          )}
        </div>
      </div>
    </PageShell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-white/50">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function SettingSlider({
  label,
  value,
  unit,
  min,
  max,
  step,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div className={cn(disabled && 'opacity-60')}>
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-sm text-white/70">{label}</div>
        <div className="text-sm font-mono text-white/90">
          {value}
          {unit}
        </div>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        disabled={disabled}
        onValueChange={([v]) => onChange(v)}
      />
    </div>
  );
}
