import { PageShell } from './PageShell';

export function HomePage() {
  return (
    <PageShell title="Welcome">
      <p className="text-white/80">
        DRX — computer-controlled knee decompression therapy. Select Setup to explore individual
        actuator controls, or Protocols to run a guided treatment sequence.
      </p>
    </PageShell>
  );
}
