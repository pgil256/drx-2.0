import { Scene } from './scene/Scene';
import { useSimTick } from './sim/useSimTick';
import { useAppStore } from './store/useAppStore';
import { BottomNav } from './ui/BottomNav';
import { PageRouter } from './ui/pages/PageRouter';
import { TopBar } from './ui/TopBar';
import { VideoDialog } from './ui/VideoDialog';

if (typeof window !== 'undefined') {
  (window as unknown as { store: typeof useAppStore }).store = useAppStore;
}

export default function App() {
  useSimTick();
  return (
    <div className="dark w-screen h-screen bg-black text-white flex flex-col">
      <TopBar />
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <aside className="md:w-96 md:shrink-0 max-h-[45vh] md:max-h-none overflow-auto border-b md:border-b-0 md:border-r border-white/10 bg-black/40 backdrop-blur-md">
          <PageRouter />
        </aside>
        <main className="flex-1 relative min-h-0 min-w-0">
          <Scene />
        </main>
      </div>
      <BottomNav />
      <VideoDialog />
    </div>
  );
}
