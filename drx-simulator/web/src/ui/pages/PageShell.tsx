import { type ReactNode } from 'react';

export function PageShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="absolute bottom-20 left-6 right-6 max-w-4xl mx-auto">
      <div className="bg-black/50 backdrop-blur-md border border-white/10 rounded-lg p-6 text-white pointer-events-auto max-h-[60vh] overflow-auto">
        <h2 className="text-xl font-medium mb-4">{title}</h2>
        {children}
      </div>
    </div>
  );
}
