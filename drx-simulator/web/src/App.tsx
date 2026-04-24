import { Scene } from './scene/Scene';
import { useSimTick } from './sim/useSimTick';
import { useAppStore } from './store/useAppStore';
import { BottomNav } from './ui/BottomNav';
import { TopBar } from './ui/TopBar';

if (typeof window !== 'undefined') {
  (window as unknown as { store: typeof useAppStore }).store = useAppStore;
}

export default function App() {
  useSimTick();
  return (
    <div className="relative w-screen h-screen bg-black">
      <Scene />
      <div className="absolute inset-0 pointer-events-none">
        <TopBar />
        <BottomNav />
      </div>
    </div>
  );
}
