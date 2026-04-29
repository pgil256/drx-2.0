import { useAppStore, type Page } from '@/store/useAppStore';
import { Button } from '@/components/ui/button';

const PAGES: Array<{ id: Page; label: string }> = [
  { id: 'home', label: 'Home' },
  { id: 'login', label: 'Login' },
  { id: 'setup', label: 'Setup' },
  { id: 'protocols', label: 'Protocols' },
  { id: 'help', label: 'Help' },
];

export function BottomNav() {
  const page = useAppStore((s) => s.ui.page);
  const setUi = useAppStore((s) => s.setUi);

  return (
    <div className="h-16 shrink-0 flex items-center justify-center gap-2 px-6 bg-black/40 backdrop-blur-md border-t border-white/10">
      {PAGES.map((p) => (
        <Button
          key={p.id}
          variant={page === p.id ? 'default' : 'ghost'}
          onClick={() => setUi({ page: p.id })}
          className="min-w-24"
        >
          {p.label}
        </Button>
      ))}
      <Button variant="ghost" onClick={() => setUi({ videoOpen: true })} className="min-w-24">
        Video
      </Button>
    </div>
  );
}
