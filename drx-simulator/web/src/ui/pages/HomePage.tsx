import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { useAppStore, type Page } from '@/store/useAppStore';
import { PageShell } from './PageShell';

type QuickLink = { page: Page; title: string; blurb: string };

const LINKS: QuickLink[] = [
  { page: 'setup', title: 'Setup', blurb: 'Drive each actuator manually to verify range and feel.' },
  { page: 'protocols', title: 'Protocols', blurb: 'Run one of the four guided treatment sequences.' },
  { page: 'help', title: 'Help', blurb: 'Command reference and operating tips.' },
];

export function HomePage() {
  const setUi = useAppStore((s) => s.setUi);

  return (
    <PageShell title="Welcome">
      <p className="text-white/80 mb-5">
        DRX — computer-controlled knee decompression therapy. This is a browser-based simulator of
        the device. Pick a destination below to explore.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {LINKS.map((link) => (
          <button
            key={link.page}
            type="button"
            onClick={() => setUi({ page: link.page })}
            className="text-left rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60"
          >
            <Card size="sm" className="h-full hover:bg-white/5 transition">
              <CardContent className="space-y-1">
                <CardTitle>{link.title}</CardTitle>
                <CardDescription>{link.blurb}</CardDescription>
              </CardContent>
            </Card>
          </button>
        ))}
      </div>
    </PageShell>
  );
}
