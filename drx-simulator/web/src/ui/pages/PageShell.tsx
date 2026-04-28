import { useState, type ReactNode } from 'react';
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function PageShell({ title, children }: { title: string; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="absolute bottom-20 left-6 right-6 max-w-4xl mx-auto">
      <div className="bg-black/50 backdrop-blur-md border border-white/10 rounded-lg text-white pointer-events-auto">
        <div className="flex items-center justify-between px-6 py-4">
          <h2 className="text-xl font-medium">{title}</h2>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? 'Expand panel' : 'Collapse panel'}
          >
            {collapsed ? <ChevronUpIcon /> : <ChevronDownIcon />}
          </Button>
        </div>
        {!collapsed && <div className="px-6 pb-6 max-h-[60vh] overflow-auto">{children}</div>}
      </div>
    </div>
  );
}
