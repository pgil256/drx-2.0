import { type ReactNode } from 'react';

export function PageShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="p-6 text-white">
      <h2 className="text-xl font-medium mb-4">{title}</h2>
      {children}
    </div>
  );
}
