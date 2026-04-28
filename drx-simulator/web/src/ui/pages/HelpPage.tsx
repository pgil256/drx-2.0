import { PageShell } from './PageShell';

const COMMANDS: Array<{ cmd: string; desc: string }> = [
  { cmd: 'P<lbs>', desc: 'Set pressure target in pounds (0-80).' },
  { cmd: 'A12 <in>', desc: 'Move axial actuator to position in inches (0-4).' },
  { cmd: 'B<deg>', desc: 'Move horizontal actuator to angle in degrees (-25 to 5).' },
  { cmd: 'K <deg>', desc: 'Move lateral actuator to angle in degrees (-20 to 20).' },
  { cmd: 'J / JS', desc: 'Start / stop continuous pulse.' },
  { cmd: 'X', desc: 'Emergency stop. Latches until reset.' },
  { cmd: 'T', desc: 'Keepalive ping.' },
];

export function HelpPage() {
  return (
    <PageShell title="Help">
      <div className="space-y-5 text-white/80">
        <section>
          <h3 className="text-sm font-medium text-white mb-2">Getting started</h3>
          <ul className="list-disc pl-5 space-y-1 text-sm">
            <li>
              <span className="text-white">Setup</span> drives each actuator independently to
              verify range and feel.
            </li>
            <li>
              <span className="text-white">Protocols</span> runs one of four guided sequences:
              axial, left lateral, right lateral, or oscillating.
            </li>
            <li>
              The red <span className="text-white">E-Stop</span> in the top bar latches all motion;
              clear it to resume.
            </li>
          </ul>
        </section>

        <section>
          <h3 className="text-sm font-medium text-white mb-2">3D scene</h3>
          <ul className="list-disc pl-5 space-y-1 text-sm">
            <li>Drag to orbit, scroll to zoom, right-drag to pan.</li>
            <li>Camera presets snap to overhead, side, or three-quarter views.</li>
          </ul>
        </section>

        <section>
          <h3 className="text-sm font-medium text-white mb-2">Command reference</h3>
          <p className="text-sm mb-2">
            The simulator accepts the same single-letter commands as the real DRX firmware.
          </p>
          <div className="rounded-md border border-white/10 bg-black/30 divide-y divide-white/5">
            {COMMANDS.map((c) => (
              <div key={c.cmd} className="flex items-baseline gap-4 px-3 py-2 text-sm">
                <code className="font-mono text-emerald-300/90 min-w-24">{c.cmd}</code>
                <span className="text-white/70">{c.desc}</span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-white mb-2">Support</h3>
          <p className="text-sm">
            For full operating procedures see the DRX clinician manual. For technical issues with
            the simulator, contact your field service representative.
          </p>
        </section>
      </div>
    </PageShell>
  );
}
