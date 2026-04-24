import { Scene } from './scene/Scene';
import { useSimTick } from './sim/useSimTick';
import { useAppStore } from './store/useAppStore';

if (typeof window !== 'undefined') {
  (window as unknown as { store: typeof useAppStore }).store = useAppStore;
}

export default function App() {
  useSimTick();
  return (
    <div className="w-screen h-screen bg-black">
      <Scene />
    </div>
  );
}
