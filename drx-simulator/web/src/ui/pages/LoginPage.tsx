import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store/useAppStore';
import { PageShell } from './PageShell';

export function LoginPage() {
  const setUi = useAppStore((s) => s.setUi);
  return (
    <PageShell title="Clinician Login">
      <div className="space-y-3 max-w-sm">
        <input
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-white"
          placeholder="Username"
          defaultValue="clinician"
        />
        <input
          type="password"
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-white"
          placeholder="Password"
          defaultValue="********"
        />
        <Button onClick={() => setUi({ page: 'home' })}>Sign In</Button>
      </div>
    </PageShell>
  );
}
