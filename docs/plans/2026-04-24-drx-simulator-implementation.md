# DRX Simulator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a browser-based 3D simulator of the DRX device, mirroring the clinician console UI, for sales/investor demos.

**Architecture:** Vite + React + TypeScript SPA. Three architectural layers with strict one-way data flow: `sim/` (pure TS device model) → `store/` (Zustand) → `scene/` (react-three-fiber) + `ui/` (React). Deployed as a static site to Vercel. STEP CAD files converted once to GLB in Blender and committed as a build artifact.

**Tech Stack:** Vite 5, React 18, TypeScript 5, react-three-fiber, @react-three/drei, three.js, Zustand 4, Tailwind CSS 3, shadcn/ui, vitest.

**Reference:** Design document at `docs/plans/2026-04-24-drx-simulator-design.md`. Read this first for full context on what we're building and why.

---

## Chunk 1 — Bootstrap + Model Pipeline

Goal: a Vite+React+TS project exists at `drx-simulator/web/`, builds cleanly, renders a canvas with the DRX model (GLB) loaded, has orbit controls, and deploys to Vercel preview on push.

### Task 1.1: Scaffold the Vite project

**Files:**
- Create: `drx-simulator/web/` (entire Vite template)

**Step 1: Run Vite scaffold**

```bash
cd drx-simulator
npm create vite@latest web -- --template react-ts
```

Expected: a `web/` directory appears with `package.json`, `src/App.tsx`, `src/main.tsx`, `index.html`, `vite.config.ts`, `tsconfig.json`.

**Step 2: Install base dependencies**

```bash
cd drx-simulator/web
npm install
```

Expected: `node_modules/` populated, `package-lock.json` created.

**Step 3: Verify dev server starts**

```bash
npm run dev
```

Expected: prints `Local: http://localhost:5173/`. Ctrl-C to stop.

**Step 4: Commit**

```bash
cd /home/gilhooleyp/projects/drx-demo
git add drx-simulator/web
git commit -m "Scaffold Vite+React+TS project for DRX simulator"
```

---

### Task 1.2: Clean default template

**Files:**
- Delete: `drx-simulator/web/src/App.css`, `drx-simulator/web/src/assets/react.svg`, `drx-simulator/web/public/vite.svg`
- Modify: `drx-simulator/web/src/App.tsx`, `drx-simulator/web/src/main.tsx`

**Step 1: Verify gitignore covers node_modules and dist**

```bash
grep -E "node_modules|dist" drx-simulator/web/.gitignore
```

Expected: both present.

**Step 2: Delete default template files**

```bash
rm drx-simulator/web/src/App.css
rm drx-simulator/web/src/assets/react.svg
rm drx-simulator/web/public/vite.svg
rmdir drx-simulator/web/src/assets 2>/dev/null || true
```

**Step 3: Replace default `App.tsx` with a placeholder**

Write `drx-simulator/web/src/App.tsx`:

```tsx
export default function App() {
  return (
    <div className="w-screen h-screen bg-black text-white flex items-center justify-center">
      <p>DRX Simulator — loading...</p>
    </div>
  );
}
```

**Step 4: Replace `main.tsx` (remove App.css import)**

Write `drx-simulator/web/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

**Step 5: Commit**

```bash
git add -A drx-simulator/web
git commit -m "Clean Vite template: remove default assets and App.css"
```

---

### Task 1.3: Install and configure Tailwind CSS

**Files:**
- Create: `drx-simulator/web/tailwind.config.ts`
- Create: `drx-simulator/web/postcss.config.js`
- Modify: `drx-simulator/web/src/index.css`

**Step 1: Install Tailwind and peers**

```bash
cd drx-simulator/web
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
```

Expected: `tailwind.config.js` and `postcss.config.js` created.

**Step 2: Rename config to `.ts` and set content paths**

Write `drx-simulator/web/tailwind.config.ts`:

```ts
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
} satisfies Config;
```

Delete the auto-generated `tailwind.config.js`.

**Step 3: Replace `src/index.css` with Tailwind directives**

Write `drx-simulator/web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  background: #0a0a0a;
  font-family: Inter, system-ui, sans-serif;
}
```

**Step 4: Verify Tailwind builds**

```bash
npm run dev
```

Open `http://localhost:5173/` — should see "DRX Simulator — loading..." centered on a black background using Tailwind classes. Ctrl-C to stop.

**Step 5: Commit**

```bash
git add -A drx-simulator/web
git commit -m "Set up Tailwind CSS"
```

---

### Task 1.4: Install 3D stack and Zustand

**Step 1: Install 3D + state libraries**

```bash
cd drx-simulator/web
npm install three @react-three/fiber @react-three/drei zustand
npm install -D @types/three
```

Expected: these appear in `package.json` dependencies.

**Step 2: Install shadcn/ui prerequisites**

```bash
npm install clsx tailwind-merge lucide-react class-variance-authority
```

**Step 3: Commit**

```bash
git add -A drx-simulator/web
git commit -m "Install three.js, R3F, drei, Zustand, and shadcn/ui deps"
```

---

### Task 1.5: Document the STEP → GLB conversion

**Files:**
- Create: `drx-simulator/web/scripts/step-to-glb.md`

**Step 1: Write the conversion guide**

Write `drx-simulator/web/scripts/step-to-glb.md`:

```markdown
# STEP → GLB Conversion

One-time setup. Re-run only when CAD changes.

## Tools
- Blender 4.2 or later (STEP importer built in).

## Steps

1. Open Blender. Scene > delete default cube/light/camera.
2. File > Import > STEP > select `drx-simulator/STEP Files/Full assembly.stp`.
   Options: Scale 0.001 (mm to m), Hierarchy: Named.
3. In the Outliner, organize into 4 empty-parent groups. For each empty:
   - Rename empty to one of: `static_frame`, `horizontal_pivot`, `lateral_pivot`, `axial_slider`.
   - Position the empty at the correct pivot point (hinge axis).
   - Parent the relevant child meshes to it.
   Hierarchy: `static_frame` > `horizontal_pivot` > `lateral_pivot` > `axial_slider`.
4. Assign materials:
   - Frame, casters, electrical box: Principled BSDF, base color #5a5f66, roughness 0.6.
   - Rails, hinges: base color #8c8f94, roughness 0.3, metallic 0.9.
   - Seat accents and strap: base color #1e4fd9 (match reference renders), roughness 0.4.
5. Select all mesh objects, Object > Apply > All Transforms (fix scale).
6. Add a Decimate modifier (collapse, ratio 0.2) to dense parts. Target ~100k to 200k tris total.
7. File > Export > glTF 2.0:
   - Format: glb
   - Include: Selected Objects OFF, Custom Properties ON
   - Transform: +Y Up ON
   - Geometry: Apply Modifiers ON, Draco compression ON (level 6)
   - Destination: `drx-simulator/web/public/models/drx.glb`
8. Verify the exported file:
   - Size: should be under 5 MB.
   - Open in https://gltf-viewer.donmccurdy.com/ to confirm the 4 named groups are visible.

## Verification

Load in the app (Task 1.7). The four transform groups must resolve via `scene.getObjectByName('static_frame')` etc. If any are missing, re-check Outliner names.
```

**Step 2: Commit**

```bash
git add drx-simulator/web/scripts/step-to-glb.md
git commit -m "Document STEP to GLB conversion workflow"
```

---

### Task 1.6: Perform the STEP → GLB conversion

**Manual step — requires Blender. If the executing engineer does not have Blender installed, flag it to the user and pause.**

**Step 1: Follow `drx-simulator/web/scripts/step-to-glb.md` exactly.**

**Step 2: Verify output**

```bash
ls -lh drx-simulator/web/public/models/drx.glb
```

Expected: file exists, size between 500 KB and 5 MB.

**Step 3: Commit the GLB**

```bash
git add drx-simulator/web/public/models/drx.glb
git commit -m "Add converted GLB model (built from STEP files)"
```

---

### Task 1.7: Render the GLB in a bare R3F canvas with orbit controls

**Files:**
- Create: `drx-simulator/web/src/scene/Scene.tsx`
- Create: `drx-simulator/web/src/scene/DeviceModel.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Write `DeviceModel.tsx`**

```tsx
import { useGLTF } from '@react-three/drei';

export function DeviceModel() {
  const { scene } = useGLTF('/models/drx.glb');
  return <primitive object={scene} />;
}

useGLTF.preload('/models/drx.glb');
```

**Step 2: Write `Scene.tsx`**

```tsx
import { Canvas } from '@react-three/fiber';
import { Environment, OrbitControls, Bounds } from '@react-three/drei';
import { Suspense } from 'react';
import { DeviceModel } from './DeviceModel';

export function Scene() {
  return (
    <Canvas camera={{ position: [2, 1.5, 2.5], fov: 45 }} shadows>
      <Suspense fallback={null}>
        <Environment preset="studio" />
        <directionalLight position={[3, 5, 3]} intensity={1.2} castShadow />
        <Bounds fit clip observe margin={1.2}>
          <DeviceModel />
        </Bounds>
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      </Suspense>
    </Canvas>
  );
}
```

**Step 3: Wire `Scene` into `App.tsx`**

```tsx
import { Scene } from './scene/Scene';

export default function App() {
  return (
    <div className="w-screen h-screen bg-black">
      <Scene />
    </div>
  );
}
```

**Step 4: Verify visually**

```bash
cd drx-simulator/web
npm run dev
```

Open `http://localhost:5173/`. Expected:
- The DRX device renders, auto-fit to the viewport.
- Left-click + drag rotates the camera.
- Right-click + drag pans.
- Scroll zooms.
- No console errors.

Ctrl-C to stop.

**Step 5: Commit**

```bash
git add -A drx-simulator/web/src
git commit -m "Render DRX GLB model in R3F canvas with orbit controls"
```

---

### Task 1.8: Add Vercel config and deploy preview

**Files:**
- Create: `drx-simulator/web/vercel.json`

**Step 1: Write `vercel.json`**

```json
{
  "framework": "vite",
  "cleanUrls": true
}
```

**Step 2: Verify production build succeeds**

```bash
cd drx-simulator/web
npm run build
```

Expected: `dist/` directory created. No errors. `dist/assets/` contains hashed JS/CSS bundles. `dist/models/drx.glb` copied from `public/`.

**Step 3: Preview the build locally**

```bash
npm run preview
```

Open the printed URL. Confirm the 3D model still loads in the production build. Ctrl-C to stop.

**Step 4: Commit**

```bash
git add drx-simulator/web/vercel.json
git commit -m "Add Vercel config for simulator deployment"
```

**Step 5: Deploy (user-driven)**

Tell the user: "Chunk 1 is shippable. Push the branch and connect `drx-simulator/web/` as a Vercel project (or `vercel --cwd drx-simulator/web --prod`) to get a live preview URL."

---

## Chunk 2 — Sim Core + Store

Goal: a pure-TS `SimulatedDevice` that accepts firmware-style commands, a Zustand store holding device + session + UI state, a 60 fps tick loop that eases actuators toward targets, and vitest unit tests.

### Task 2.1: Install vitest and set up test runner

**Step 1: Install**

```bash
cd drx-simulator/web
npm install -D vitest @vitest/ui jsdom
```

**Step 2: Add test script to `package.json`**

Modify `drx-simulator/web/package.json` `scripts`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

**Step 3: Add vitest config**

Rewrite `drx-simulator/web/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    globals: true,
  },
});
```

**Step 4: Verify test runner works**

```bash
npm run test
```

Expected: "No test files found" (benign; exit code may be 1 — that's fine for now).

**Step 5: Commit**

```bash
git add drx-simulator/web/package.json drx-simulator/web/vite.config.ts drx-simulator/web/package-lock.json
git commit -m "Install vitest and configure test runner"
```

---

### Task 2.2: Write the device state types

**Files:**
- Create: `drx-simulator/web/src/sim/types.ts`

**Step 1: Write types**

```ts
export type ActuatorState = {
  pos: number;
  target: number;
  moving: boolean;
};

export type PressureState = {
  lbs: number;
  target: number;
};

export type DeviceState = {
  axial: ActuatorState;       // inches, 0..4
  horizontal: ActuatorState;  // degrees, -25..+5
  lateral: ActuatorState;     // degrees, -20..+20
  pressure: PressureState;    // lbs, 0..80
  pulsing: boolean;
  eStop: boolean;
};

export const INITIAL_DEVICE_STATE: DeviceState = {
  axial: { pos: 0, target: 0, moving: false },
  horizontal: { pos: -15, target: -15, moving: false },
  lateral: { pos: 0, target: 0, moving: false },
  pressure: { lbs: 0, target: 0 },
  pulsing: false,
  eStop: false,
};

export const LIMITS = {
  axial: { min: 0, max: 4 },
  horizontal: { min: -25, max: 5 },
  lateral: { min: -20, max: 20 },
  pressure: { min: 0, max: 80 },
} as const;

export const SPEEDS = {
  axial: 1.0,        // in/sec
  horizontal: 30,    // deg/sec
  lateral: 30,       // deg/sec
  pressure: 20,      // lbs/sec
} as const;
```

**Step 2: Commit**

```bash
git add drx-simulator/web/src/sim/types.ts
git commit -m "Add device state types and limits"
```

---

### Task 2.3: Command parser — test first

**Files:**
- Create: `drx-simulator/web/src/sim/parseCommand.test.ts`
- Create: `drx-simulator/web/src/sim/parseCommand.ts`

**Step 1: Write the failing tests**

```ts
import { describe, it, expect } from 'vitest';
import { parseCommand } from './parseCommand';

describe('parseCommand', () => {
  it('parses axial commands (A12 <value>)', () => {
    expect(parseCommand('A12 2.5')).toEqual({ kind: 'axial', value: 2.5 });
    expect(parseCommand('A12 0')).toEqual({ kind: 'axial', value: 0 });
  });

  it('parses horizontal commands (B<value>)', () => {
    expect(parseCommand('B-15')).toEqual({ kind: 'horizontal', value: -15 });
    expect(parseCommand('B5')).toEqual({ kind: 'horizontal', value: 5 });
  });

  it('parses lateral commands (K <value>)', () => {
    expect(parseCommand('K -20')).toEqual({ kind: 'lateral', value: -20 });
    expect(parseCommand('K 20')).toEqual({ kind: 'lateral', value: 20 });
  });

  it('parses pressure commands (P<value>)', () => {
    expect(parseCommand('P40')).toEqual({ kind: 'pressure', value: 40 });
  });

  it('parses pulse toggles J and JS', () => {
    expect(parseCommand('J')).toEqual({ kind: 'pulseStart' });
    expect(parseCommand('JS')).toEqual({ kind: 'pulseStop' });
  });

  it('parses emergency stop X', () => {
    expect(parseCommand('X')).toEqual({ kind: 'eStop' });
  });

  it('parses keepalive T', () => {
    expect(parseCommand('T')).toEqual({ kind: 'keepalive' });
  });

  it('returns null for unknown commands', () => {
    expect(parseCommand('Z99')).toBeNull();
    expect(parseCommand('')).toBeNull();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
npm run test -- parseCommand
```

Expected: FAIL — `parseCommand` not found.

**Step 3: Implement `parseCommand.ts`**

Note: uses `String.prototype.match()` (not `RegExp.prototype.exec()`). Equivalent for non-global regexes and avoids some linters flagging regex execution.

```ts
export type ParsedCommand =
  | { kind: 'axial'; value: number }
  | { kind: 'horizontal'; value: number }
  | { kind: 'lateral'; value: number }
  | { kind: 'pressure'; value: number }
  | { kind: 'pulseStart' }
  | { kind: 'pulseStop' }
  | { kind: 'eStop' }
  | { kind: 'keepalive' };

export function parseCommand(raw: string): ParsedCommand | null {
  const s = raw.trim();
  if (s === 'J') return { kind: 'pulseStart' };
  if (s === 'JS') return { kind: 'pulseStop' };
  if (s === 'X') return { kind: 'eStop' };
  if (s === 'T') return { kind: 'keepalive' };

  const axialMatch = s.match(/^A12\s+(-?\d+(?:\.\d+)?)$/);
  if (axialMatch) return { kind: 'axial', value: parseFloat(axialMatch[1]) };

  const horizontalMatch = s.match(/^B(-?\d+(?:\.\d+)?)$/);
  if (horizontalMatch) return { kind: 'horizontal', value: parseFloat(horizontalMatch[1]) };

  const lateralMatch = s.match(/^K\s+(-?\d+(?:\.\d+)?)$/);
  if (lateralMatch) return { kind: 'lateral', value: parseFloat(lateralMatch[1]) };

  const pressureMatch = s.match(/^P(-?\d+(?:\.\d+)?)$/);
  if (pressureMatch) return { kind: 'pressure', value: parseFloat(pressureMatch[1]) };

  return null;
}
```

**Step 4: Run tests to verify they pass**

```bash
npm run test -- parseCommand
```

Expected: all 8 tests PASS.

**Step 5: Commit**

```bash
git add drx-simulator/web/src/sim
git commit -m "Add command parser for simulated device"
```

---

### Task 2.4: Easing tick function — test first

**Files:**
- Create: `drx-simulator/web/src/sim/step.test.ts`
- Create: `drx-simulator/web/src/sim/step.ts`

**Step 1: Write the failing tests**

```ts
import { describe, it, expect } from 'vitest';
import { stepActuator } from './step';

describe('stepActuator', () => {
  it('moves toward target at the given speed', () => {
    const next = stepActuator({ pos: 0, target: 2, moving: true }, 1.0, 0.5);
    expect(next.pos).toBeCloseTo(0.5, 5);
    expect(next.moving).toBe(true);
  });

  it('clamps to target and clears moving flag when within step size', () => {
    const next = stepActuator({ pos: 1.9, target: 2, moving: true }, 1.0, 0.5);
    expect(next.pos).toBe(2);
    expect(next.moving).toBe(false);
  });

  it('moves backwards when target is less than position', () => {
    const next = stepActuator({ pos: 2, target: 0, moving: true }, 1.0, 0.5);
    expect(next.pos).toBeCloseTo(1.5, 5);
    expect(next.moving).toBe(true);
  });

  it('does nothing when not moving', () => {
    const next = stepActuator({ pos: 1, target: 2, moving: false }, 1.0, 0.5);
    expect(next.pos).toBe(1);
    expect(next.moving).toBe(false);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
npm run test -- step
```

Expected: FAIL — `stepActuator` not found.

**Step 3: Implement `step.ts`**

```ts
import type { ActuatorState } from './types';

export function stepActuator(
  state: ActuatorState,
  speedPerSec: number,
  dtSec: number,
): ActuatorState {
  if (!state.moving) return state;

  const delta = state.target - state.pos;
  const maxStep = speedPerSec * dtSec;

  if (Math.abs(delta) <= maxStep) {
    return { pos: state.target, target: state.target, moving: false };
  }

  const direction = Math.sign(delta);
  return { ...state, pos: state.pos + direction * maxStep };
}
```

**Step 4: Run tests to verify they pass**

```bash
npm run test -- step
```

Expected: 4 tests PASS.

**Step 5: Commit**

```bash
git add drx-simulator/web/src/sim/step.ts drx-simulator/web/src/sim/step.test.ts
git commit -m "Add easing step function for actuators"
```

---

### Task 2.5: Zustand store slices

**Files:**
- Create: `drx-simulator/web/src/store/useAppStore.ts`

**Step 1: Write the store**

```ts
import { create } from 'zustand';
import { INITIAL_DEVICE_STATE, type DeviceState } from '../sim/types';

export type Page = 'home' | 'login' | 'setup' | 'protocols' | 'help';
export type SetupTab = 'axial' | 'horizontal' | 'lateral';
export type ProtocolId = 1 | 2 | 3 | 4;

type SessionState = {
  runningProtocol: ProtocolId | null;
  progressPct: number;       // 0..100
  elapsedSec: number;
  durationSec: number;
  maxPressure: number;       // lbs
  usePulse: boolean;
};

type UiState = {
  page: Page;
  setupTab: SetupTab;
  videoOpen: boolean;
  helpOpen: boolean;
  cameraPreset: 'three-quarter' | 'side' | 'overhead';
};

type AppState = {
  device: DeviceState;
  session: SessionState;
  ui: UiState;

  setDevice: (patch: Partial<DeviceState>) => void;
  setAxialTarget: (v: number) => void;
  setHorizontalTarget: (v: number) => void;
  setLateralTarget: (v: number) => void;
  setPressureTarget: (v: number) => void;
  setPulsing: (v: boolean) => void;
  setEStop: (v: boolean) => void;

  setSession: (patch: Partial<SessionState>) => void;
  setUi: (patch: Partial<UiState>) => void;
};

export const useAppStore = create<AppState>((set) => ({
  device: INITIAL_DEVICE_STATE,
  session: {
    runningProtocol: null,
    progressPct: 0,
    elapsedSec: 0,
    durationSec: 30,
    maxPressure: 40,
    usePulse: false,
  },
  ui: {
    page: 'home',
    setupTab: 'axial',
    videoOpen: false,
    helpOpen: false,
    cameraPreset: 'three-quarter',
  },

  setDevice: (patch) => set((s) => ({ device: { ...s.device, ...patch } })),
  setAxialTarget: (v) =>
    set((s) => ({
      device: { ...s.device, axial: { ...s.device.axial, target: v, moving: true } },
    })),
  setHorizontalTarget: (v) =>
    set((s) => ({
      device: { ...s.device, horizontal: { ...s.device.horizontal, target: v, moving: true } },
    })),
  setLateralTarget: (v) =>
    set((s) => ({
      device: { ...s.device, lateral: { ...s.device.lateral, target: v, moving: true } },
    })),
  setPressureTarget: (v) =>
    set((s) => ({
      device: { ...s.device, pressure: { ...s.device.pressure, target: v } },
    })),
  setPulsing: (v) => set((s) => ({ device: { ...s.device, pulsing: v } })),
  setEStop: (v) => set((s) => ({ device: { ...s.device, eStop: v } })),

  setSession: (patch) => set((s) => ({ session: { ...s.session, ...patch } })),
  setUi: (patch) => set((s) => ({ ui: { ...s.ui, ...patch } })),
}));
```

**Step 2: Commit**

```bash
git add drx-simulator/web/src/store
git commit -m "Add Zustand store for device, session, and UI state"
```

---

### Task 2.6: SimulatedDevice class

**Files:**
- Create: `drx-simulator/web/src/sim/SimulatedDevice.ts`
- Create: `drx-simulator/web/src/sim/SimulatedDevice.test.ts`

**Step 1: Write the tests**

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { SimulatedDevice } from './SimulatedDevice';
import { useAppStore } from '../store/useAppStore';
import { INITIAL_DEVICE_STATE } from './types';

describe('SimulatedDevice', () => {
  beforeEach(() => {
    useAppStore.setState({ device: structuredClone(INITIAL_DEVICE_STATE) });
  });

  it('sets axial target on valid A12 command', () => {
    const dev = new SimulatedDevice();
    dev.send('A12 2.5');
    expect(useAppStore.getState().device.axial.target).toBe(2.5);
    expect(useAppStore.getState().device.axial.moving).toBe(true);
  });

  it('clamps axial target within limits', () => {
    const dev = new SimulatedDevice();
    dev.send('A12 99');
    expect(useAppStore.getState().device.axial.target).toBe(4);
    dev.send('A12 -5');
    expect(useAppStore.getState().device.axial.target).toBe(0);
  });

  it('latches eStop on X command and freezes motion', () => {
    const dev = new SimulatedDevice();
    dev.send('A12 2');
    dev.send('X');
    expect(useAppStore.getState().device.eStop).toBe(true);
    dev.tick(1.0);
    expect(useAppStore.getState().device.axial.pos).toBe(0);
  });

  it('tick advances actuators toward targets', () => {
    const dev = new SimulatedDevice();
    dev.send('A12 2');
    dev.tick(1.0); // 1 second at 1 in/sec = 1 inch
    expect(useAppStore.getState().device.axial.pos).toBeCloseTo(1, 5);
  });

  it('ignores unknown commands silently', () => {
    const dev = new SimulatedDevice();
    expect(() => dev.send('ZZZ')).not.toThrow();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
npm run test -- SimulatedDevice
```

Expected: FAIL — class not defined.

**Step 3: Implement `SimulatedDevice.ts`**

```ts
import { useAppStore } from '../store/useAppStore';
import { parseCommand } from './parseCommand';
import { stepActuator } from './step';
import { LIMITS, SPEEDS } from './types';

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

export class SimulatedDevice {
  send(raw: string): void {
    const parsed = parseCommand(raw);
    if (!parsed) return;

    const s = useAppStore.getState();
    if (s.device.eStop && parsed.kind !== 'eStop') return;

    switch (parsed.kind) {
      case 'axial':
        s.setAxialTarget(clamp(parsed.value, LIMITS.axial.min, LIMITS.axial.max));
        break;
      case 'horizontal':
        s.setHorizontalTarget(clamp(parsed.value, LIMITS.horizontal.min, LIMITS.horizontal.max));
        break;
      case 'lateral':
        s.setLateralTarget(clamp(parsed.value, LIMITS.lateral.min, LIMITS.lateral.max));
        break;
      case 'pressure':
        s.setPressureTarget(clamp(parsed.value, LIMITS.pressure.min, LIMITS.pressure.max));
        break;
      case 'pulseStart':
        s.setPulsing(true);
        break;
      case 'pulseStop':
        s.setPulsing(false);
        break;
      case 'eStop':
        s.setEStop(true);
        s.setPressureTarget(0);
        useAppStore.setState((prev) => ({
          device: {
            ...prev.device,
            axial: { ...prev.device.axial, moving: false },
            horizontal: { ...prev.device.horizontal, moving: false },
            lateral: { ...prev.device.lateral, moving: false },
          },
        }));
        break;
      case 'keepalive':
        break;
    }
  }

  tick(dtSec: number): void {
    const { device } = useAppStore.getState();
    if (device.eStop) return;

    const axial = stepActuator(device.axial, SPEEDS.axial, dtSec);
    const horizontal = stepActuator(device.horizontal, SPEEDS.horizontal, dtSec);
    const lateral = stepActuator(device.lateral, SPEEDS.lateral, dtSec);

    const pDelta = device.pressure.target - device.pressure.lbs;
    const pMax = SPEEDS.pressure * dtSec;
    const pressureLbs =
      Math.abs(pDelta) <= pMax
        ? device.pressure.target
        : device.pressure.lbs + Math.sign(pDelta) * pMax;

    useAppStore.setState({
      device: {
        ...device,
        axial,
        horizontal,
        lateral,
        pressure: { ...device.pressure, lbs: pressureLbs },
      },
    });
  }

  resetEStop(): void {
    useAppStore.getState().setEStop(false);
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
npm run test
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add drx-simulator/web/src/sim
git commit -m "Add SimulatedDevice with command dispatch and tick integration"
```

---

### Task 2.7: RAF tick loop

**Files:**
- Create: `drx-simulator/web/src/sim/useSimTick.ts`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Write the hook**

```ts
import { useEffect, useRef } from 'react';
import { SimulatedDevice } from './SimulatedDevice';

export const simDevice = new SimulatedDevice();

export function useSimTick() {
  const lastTimeRef = useRef<number | null>(null);

  useEffect(() => {
    let rafId = 0;
    const tick = (now: number) => {
      if (lastTimeRef.current == null) lastTimeRef.current = now;
      const dt = (now - lastTimeRef.current) / 1000;
      lastTimeRef.current = now;
      simDevice.tick(Math.min(dt, 0.1)); // cap at 100ms to absorb tab-sleep jank
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);
}
```

**Step 2: Wire it up in `App.tsx`**

```tsx
import { Scene } from './scene/Scene';
import { useSimTick } from './sim/useSimTick';

export default function App() {
  useSimTick();
  return (
    <div className="w-screen h-screen bg-black">
      <Scene />
    </div>
  );
}
```

**Step 3: Verify**

```bash
npm run dev
```

App still renders the model, no errors. Real verification comes in chunk 3.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add RAF tick loop driving SimulatedDevice"
```

---

## Chunk 3 — Scene Rigging

Goal: 3D model's four transform groups respond to store changes; pressure visual cue works; 3 camera presets selectable.

### Task 3.1: Drive transforms from the store in useFrame

**Files:**
- Modify: `drx-simulator/web/src/scene/DeviceModel.tsx`

**Step 1: Rewrite `DeviceModel.tsx`**

```tsx
import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import type { Object3D } from 'three';
import { useAppStore } from '../store/useAppStore';

const IN_TO_M = 0.0254;

function degToRad(deg: number) {
  return (deg * Math.PI) / 180;
}

export function DeviceModel() {
  const { scene } = useGLTF('/models/drx.glb');

  const axialRef = useRef<Object3D | null>(null);
  const lateralRef = useRef<Object3D | null>(null);
  const horizontalRef = useRef<Object3D | null>(null);

  useEffect(() => {
    axialRef.current = scene.getObjectByName('axial_slider') ?? null;
    lateralRef.current = scene.getObjectByName('lateral_pivot') ?? null;
    horizontalRef.current = scene.getObjectByName('horizontal_pivot') ?? null;

    if (!axialRef.current || !lateralRef.current || !horizontalRef.current) {
      console.warn(
        'DeviceModel: pivot groups not found. Expected: axial_slider, lateral_pivot, horizontal_pivot',
      );
    }
  }, [scene]);

  useFrame(() => {
    const d = useAppStore.getState().device;
    if (axialRef.current) axialRef.current.position.z = d.axial.pos * IN_TO_M;
    if (lateralRef.current) lateralRef.current.rotation.y = degToRad(d.lateral.pos);
    if (horizontalRef.current) horizontalRef.current.rotation.x = degToRad(d.horizontal.pos);
  });

  return <primitive object={scene} />;
}

useGLTF.preload('/models/drx.glb');
```

**Step 2: Verify visually**

```bash
npm run dev
```

Expose the store temporarily for debugging: at top of `App.tsx` add:

```tsx
import { useAppStore } from './store/useAppStore';
(window as any).store = useAppStore;
```

In browser DevTools console:

```js
window.store.getState().setAxialTarget(3);
window.store.getState().setLateralTarget(20);
window.store.getState().setHorizontalTarget(-25);
```

Expected: the leg extends forward, swings right, tilts. If directions are wrong, flip signs in `DeviceModel.tsx`.

**Step 3: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Wire store to GLB transform groups for actuator motion"
```

---

### Task 3.2: Pressure glow effect

**Files:**
- Modify: `drx-simulator/web/src/scene/DeviceModel.tsx`

**Step 1: Find the strap/leg mesh names**

In DevTools console:

```js
// Walk the loaded model, log mesh names
const { scene } = (await import('three/examples/jsm/loaders/GLTFLoader.js'));
// Simpler: place this temporarily in useEffect of DeviceModel and check console:
scene.traverse((o) => o.isMesh && console.log(o.name));
```

Note which names correspond to strap and bent-leg parts (likely "Traction_body", "Bent_leg"). Update the list below.

**Step 2: Extend `DeviceModel.tsx`**

Add to the component:

```tsx
const strapMeshesRef = useRef<any[]>([]);

useEffect(() => {
  const strapNames = ['Traction_body', 'Bent_leg', 'Bent_leg_2']; // adjust after inspection
  strapMeshesRef.current = [];
  scene.traverse((obj: any) => {
    if (obj.isMesh && strapNames.includes(obj.name)) {
      obj.material = obj.material.clone();
      obj.material.emissive?.setHex?.(0xff2a2a);
      obj.material.emissiveIntensity = 0;
      strapMeshesRef.current.push(obj);
    }
  });
}, [scene]);

// In useFrame (append to existing):
const pressureFrac = d.pressure.lbs / 80;
for (const obj of strapMeshesRef.current) {
  obj.material.emissiveIntensity = pressureFrac * 0.8;
}
```

**Step 3: Verify**

`npm run dev`. In console:

```js
window.store.getState().setPressureTarget(60);
```

Strap glows red over ~3 seconds. Setting to 0 fades out.

**Step 4: Commit**

```bash
git add drx-simulator/web/src/scene/DeviceModel.tsx
git commit -m "Add pressure emissive glow on strap materials"
```

---

### Task 3.3: Camera presets

**Files:**
- Create: `drx-simulator/web/src/scene/cameraPresets.ts`
- Modify: `drx-simulator/web/src/scene/Scene.tsx`

**Step 1: Define presets**

```ts
import type { Vector3Tuple } from 'three';

export type CameraPreset = {
  id: 'overhead' | 'side' | 'three-quarter';
  label: string;
  position: Vector3Tuple;
  target: Vector3Tuple;
};

export const CAMERA_PRESETS: CameraPreset[] = [
  { id: 'three-quarter', label: '3/4 View', position: [2.2, 1.5, 2.5], target: [0, 0.6, 0] },
  { id: 'side',          label: 'Side',     position: [3.5, 0.8, 0],   target: [0, 0.6, 0] },
  { id: 'overhead',      label: 'Overhead', position: [0, 4, 0.01],    target: [0, 0, 0] },
];
```

**Step 2: Rewrite `Scene.tsx`**

```tsx
import { Canvas, useThree } from '@react-three/fiber';
import { Environment, OrbitControls } from '@react-three/drei';
import { Suspense, useEffect } from 'react';
import { DeviceModel } from './DeviceModel';
import { CAMERA_PRESETS } from './cameraPresets';
import { useAppStore } from '../store/useAppStore';

function CameraRig() {
  const { camera } = useThree();
  const presetId = useAppStore((s) => s.ui.cameraPreset);
  useEffect(() => {
    const p = CAMERA_PRESETS.find((x) => x.id === presetId) ?? CAMERA_PRESETS[0];
    camera.position.set(...p.position);
    camera.lookAt(...p.target);
  }, [presetId, camera]);
  return null;
}

export function Scene() {
  return (
    <Canvas camera={{ position: [2.2, 1.5, 2.5], fov: 45 }} shadows>
      <Suspense fallback={null}>
        <Environment preset="studio" />
        <directionalLight position={[3, 5, 3]} intensity={1.2} castShadow />
        <DeviceModel />
        <CameraRig />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      </Suspense>
    </Canvas>
  );
}
```

(Dropped `<Bounds>` — with explicit presets, auto-fit fights the user.)

**Step 3: Verify in console**

```js
window.store.getState().setUi({ cameraPreset: 'side' });
```

Camera snaps to side view.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add three camera presets (overhead, side, 3/4)"
```

---

## Chunk 4 — UI Shell + Setup Page

Goal: clinician console UI chrome floats over the canvas; bottom nav switches pages; Setup page has working per-actuator tabs wired to the sim.

### Task 4.1: Install shadcn/ui primitives

**Step 1: Initialize shadcn**

```bash
cd drx-simulator/web
npx shadcn@latest init
```

Prompts:
- Style: Default
- Base color: Slate
- CSS variables: Yes

**Step 2: Install primitives**

```bash
npx shadcn@latest add button slider tabs card dialog badge
```

Expected: `src/components/ui/` populated.

**Step 3: Commit**

```bash
git add -A drx-simulator/web
git commit -m "Install shadcn/ui primitives"
```

---

### Task 4.2: Top bar with E-Stop

**Files:**
- Create: `drx-simulator/web/src/ui/TopBar.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Write `TopBar.tsx`**

```tsx
import { Button } from '../components/ui/button';
import { useAppStore } from '../store/useAppStore';
import { simDevice } from '../sim/useSimTick';

export function TopBar() {
  const eStop = useAppStore((s) => s.device.eStop);

  return (
    <div className="absolute top-0 left-0 right-0 h-14 flex items-center justify-between px-6 bg-black/40 backdrop-blur-md border-b border-white/10 pointer-events-auto">
      <div className="text-white font-medium tracking-wide">DRX Simulator</div>
      {eStop ? (
        <Button variant="destructive" onClick={() => simDevice.resetEStop()}>
          Reset E-Stop
        </Button>
      ) : (
        <Button variant="destructive" onClick={() => simDevice.send('X')}>
          E-STOP
        </Button>
      )}
    </div>
  );
}
```

**Step 2: Render in `App.tsx`**

```tsx
import { Scene } from './scene/Scene';
import { useSimTick } from './sim/useSimTick';
import { TopBar } from './ui/TopBar';

export default function App() {
  useSimTick();
  return (
    <div className="relative w-screen h-screen bg-black">
      <Scene />
      <div className="absolute inset-0 pointer-events-none">
        <TopBar />
      </div>
    </div>
  );
}
```

**Step 3: Verify**

Top bar with title and red E-Stop button. Click it — button flips to "Reset E-Stop", motion halts. Click again — resets.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add top bar with E-Stop button"
```

---

### Task 4.3: Bottom navigation

**Files:**
- Create: `drx-simulator/web/src/ui/BottomNav.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Write `BottomNav.tsx`**

```tsx
import { useAppStore, type Page } from '../store/useAppStore';
import { Button } from '../components/ui/button';

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
    <div className="absolute bottom-0 left-0 right-0 h-16 flex items-center justify-center gap-2 px-6 bg-black/40 backdrop-blur-md border-t border-white/10 pointer-events-auto">
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
```

**Step 2: Add to `App.tsx`**

```tsx
import { BottomNav } from './ui/BottomNav';

// in JSX, inside the pointer-events-none wrapper:
<TopBar />
<BottomNav />
```

**Step 3: Verify**

Bottom nav appears with 6 buttons. Active state updates on click.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add bottom navigation bar"
```

---

### Task 4.4: Page shell + stub pages

**Files:**
- Create: `drx-simulator/web/src/ui/pages/PageShell.tsx`
- Create: `drx-simulator/web/src/ui/pages/HomePage.tsx`
- Create: `drx-simulator/web/src/ui/pages/LoginPage.tsx`
- Create: `drx-simulator/web/src/ui/pages/HelpPage.tsx`
- Create: `drx-simulator/web/src/ui/pages/SetupPage.tsx` (stub)
- Create: `drx-simulator/web/src/ui/pages/ProtocolsPage.tsx` (stub)
- Create: `drx-simulator/web/src/ui/pages/PageRouter.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: `PageShell.tsx`**

```tsx
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
```

**Step 2: Stub pages**

`HomePage.tsx`:

```tsx
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
```

`LoginPage.tsx`:

```tsx
import { PageShell } from './PageShell';
import { Button } from '../../components/ui/button';
import { useAppStore } from '../../store/useAppStore';

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
```

`HelpPage.tsx`:

```tsx
import { PageShell } from './PageShell';

export function HelpPage() {
  return (
    <PageShell title="Help">
      <p className="text-white/80">
        For full operating procedures, see the DRX clinician manual. For technical support, contact
        your field service representative.
      </p>
    </PageShell>
  );
}
```

`SetupPage.tsx` (stub):

```tsx
import { PageShell } from './PageShell';

export function SetupPage() {
  return <PageShell title="Setup">Setup controls coming in the next task.</PageShell>;
}
```

`ProtocolsPage.tsx` (stub):

```tsx
import { PageShell } from './PageShell';

export function ProtocolsPage() {
  return <PageShell title="Protocols">Protocol controls coming in chunk 5.</PageShell>;
}
```

**Step 3: `PageRouter.tsx`**

```tsx
import { useAppStore } from '../../store/useAppStore';
import { HomePage } from './HomePage';
import { LoginPage } from './LoginPage';
import { SetupPage } from './SetupPage';
import { ProtocolsPage } from './ProtocolsPage';
import { HelpPage } from './HelpPage';

export function PageRouter() {
  const page = useAppStore((s) => s.ui.page);
  switch (page) {
    case 'home': return <HomePage />;
    case 'login': return <LoginPage />;
    case 'setup': return <SetupPage />;
    case 'protocols': return <ProtocolsPage />;
    case 'help': return <HelpPage />;
  }
}
```

**Step 4: Render in `App.tsx`**

```tsx
import { PageRouter } from './ui/pages/PageRouter';
// in JSX:
<TopBar />
<PageRouter />
<BottomNav />
```

**Step 5: Verify**

Click each nav button, corresponding page appears. Login's "Sign In" sends to Home.

**Step 6: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add page shell, stub pages, and page router"
```

---

### Task 4.5: Setup page with actuator tabs

**Files:**
- Modify: `drx-simulator/web/src/ui/pages/SetupPage.tsx`
- Create: `drx-simulator/web/src/ui/pages/ActuatorPanel.tsx`

**Step 1: `ActuatorPanel.tsx`**

```tsx
import { Button } from '../../components/ui/button';
import { Slider } from '../../components/ui/slider';
import { useAppStore } from '../../store/useAppStore';
import { LIMITS } from '../../sim/types';
import { simDevice } from '../../sim/useSimTick';

type Actuator = 'axial' | 'horizontal' | 'lateral';

const CONFIG: Record<Actuator, {
  units: string;
  stepNormal: number;
  stepFast: number;
  command: (v: number) => string;
  format: (v: number) => string;
}> = {
  axial: {
    units: 'in',
    stepNormal: 0.5,
    stepFast: 1.0,
    command: (v) => `A12 ${v.toFixed(2)}`,
    format: (v) => v.toFixed(1),
  },
  horizontal: {
    units: 'deg',
    stepNormal: 5,
    stepFast: 10,
    command: (v) => `B${Math.round(v)}`,
    format: (v) => `${Math.round(v)}`,
  },
  lateral: {
    units: 'deg',
    stepNormal: 5,
    stepFast: 10,
    command: (v) => `K ${Math.round(v)}`,
    format: (v) => `${Math.round(v)}`,
  },
};

export function ActuatorPanel({ actuator }: { actuator: Actuator }) {
  const cfg = CONFIG[actuator];
  const limits = LIMITS[actuator];
  const state = useAppStore((s) => s.device[actuator]);
  const pressure = useAppStore((s) => s.device.pressure);

  const nudge = (delta: number) => {
    const next = Math.max(limits.min, Math.min(limits.max, state.target + delta));
    simDevice.send(cfg.command(next));
  };

  return (
    <div className="grid grid-cols-2 gap-6">
      <div className="space-y-4">
        <div>
          <div className="text-sm text-white/60">Position</div>
          <div className="text-2xl font-mono">{cfg.format(state.pos)} {cfg.units}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => nudge(-cfg.stepNormal)}>Reverse</Button>
          <Button variant="secondary" onClick={() => nudge(cfg.stepNormal)}>Forward</Button>
          <Button variant="secondary" onClick={() => nudge(-cfg.stepFast)}>Fast Reverse</Button>
          <Button variant="secondary" onClick={() => nudge(cfg.stepFast)}>Fast Forward</Button>
          <Button variant="outline" onClick={() => simDevice.send(cfg.command(0))}>Reset</Button>
        </div>
        <div>
          <div className="text-sm text-white/60 mb-2">Target: {cfg.format(state.target)} {cfg.units}</div>
          <Slider
            min={limits.min}
            max={limits.max}
            step={actuator === 'axial' ? 0.1 : 1}
            value={[state.target]}
            onValueChange={([v]) => simDevice.send(cfg.command(v))}
          />
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <div className="text-sm text-white/60">Pressure</div>
          <div className="text-2xl font-mono">{pressure.lbs.toFixed(0)} lbs</div>
        </div>
        <div>
          <div className="text-sm text-white/60 mb-2">Target: {pressure.target.toFixed(0)} lbs</div>
          <Slider
            min={LIMITS.pressure.min}
            max={LIMITS.pressure.max}
            step={1}
            value={[pressure.target]}
            onValueChange={([v]) => simDevice.send(`P${Math.round(v)}`)}
          />
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => simDevice.send('P0')}>Stop Pressure</Button>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Replace `SetupPage.tsx`**

```tsx
import { PageShell } from './PageShell';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs';
import { useAppStore, type SetupTab } from '../../store/useAppStore';
import { ActuatorPanel } from './ActuatorPanel';

export function SetupPage() {
  const tab = useAppStore((s) => s.ui.setupTab);
  const setUi = useAppStore((s) => s.setUi);

  return (
    <PageShell title="Setup">
      <Tabs value={tab} onValueChange={(v) => setUi({ setupTab: v as SetupTab })}>
        <TabsList>
          <TabsTrigger value="axial">Axial</TabsTrigger>
          <TabsTrigger value="horizontal">Horizontal</TabsTrigger>
          <TabsTrigger value="lateral">Lateral</TabsTrigger>
        </TabsList>
        <TabsContent value="axial"><ActuatorPanel actuator="axial" /></TabsContent>
        <TabsContent value="horizontal"><ActuatorPanel actuator="horizontal" /></TabsContent>
        <TabsContent value="lateral"><ActuatorPanel actuator="lateral" /></TabsContent>
      </Tabs>
    </PageShell>
  );
}
```

**Step 3: Verify**

`npm run dev`. Go to Setup > Axial. Drag the position slider — leg extends forward. Same for Horizontal (tilt) and Lateral (swing). Pressure slider makes the strap glow red.

**Step 4: Commit**

```bash
git add drx-simulator/web/src/ui
git commit -m "Add Setup page with per-actuator manual controls"
```

---

## Chunk 5 — Protocols Page + Polish

Goal: protocol runner executes the 4 protocols; Protocols page drives it; E-Stop banner, event log, loading screen, self-test, idle auto-demo, keyboard shortcuts all in place.

### Task 5.1: Protocol runner with AbortController

**Files:**
- Create: `drx-simulator/web/src/sim/protocolRunner.ts`
- Create: `drx-simulator/web/src/sim/protocolRunner.test.ts`

**Step 1: Write tests**

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { runProtocol } from './protocolRunner';
import { useAppStore } from '../store/useAppStore';
import { INITIAL_DEVICE_STATE } from './types';
import { simDevice } from './useSimTick';

describe('runProtocol', () => {
  beforeEach(() => {
    useAppStore.setState({ device: structuredClone(INITIAL_DEVICE_STATE) });
  });

  it('aborts cleanly when signal is triggered', async () => {
    const controller = new AbortController();
    const promise = runProtocol(2, controller.signal, {
      durationSec: 30, maxPressure: 40, usePulse: false,
    });
    controller.abort();
    await expect(promise).resolves.toBeUndefined();
  });

  it('sets runningProtocol in session during execution', async () => {
    const controller = new AbortController();
    const p = runProtocol(1, controller.signal, {
      durationSec: 5, maxPressure: 40, usePulse: false,
    });
    // Allow first microtask so session updates
    await Promise.resolve();
    expect(useAppStore.getState().session.runningProtocol).toBe(1);
    controller.abort();
    await p;
    expect(useAppStore.getState().session.runningProtocol).toBeNull();
  });
});
```

**Step 2: Implement `protocolRunner.ts`**

```ts
import { simDevice } from './useSimTick';
import { useAppStore } from '../store/useAppStore';
import type { ProtocolId } from '../store/useAppStore';

type ProtocolOpts = {
  durationSec: number;
  maxPressure: number;
  usePulse: boolean;
};

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(() => resolve(), ms);
    signal.addEventListener('abort', () => {
      clearTimeout(t);
      resolve();
    }, { once: true });
  });
}

export async function runProtocol(
  id: ProtocolId,
  signal: AbortSignal,
  opts: ProtocolOpts,
): Promise<void> {
  const store = useAppStore.getState();
  store.setSession({ runningProtocol: id, progressPct: 0, elapsedSec: 0 });

  try {
    simDevice.send('A12 3.0');
    simDevice.send(`P${opts.maxPressure}`);
    await sleep(3000, signal);
    if (signal.aborted) return;

    switch (id) {
      case 1: {
        if (opts.usePulse) simDevice.send('J');
        await sleep(Math.max(1000, opts.durationSec * 1000 - 4000), signal);
        if (opts.usePulse) simDevice.send('JS');
        break;
      }
      case 2: {
        simDevice.send('K -20');
        await sleep(2000, signal);
        await sleep(5000, signal);
        simDevice.send('K 0');
        await sleep(2000, signal);
        break;
      }
      case 3: {
        simDevice.send('K 20');
        await sleep(2000, signal);
        await sleep(5000, signal);
        simDevice.send('K 0');
        await sleep(2000, signal);
        break;
      }
      case 4: {
        const end = Date.now() + Math.max(4000, (opts.durationSec - 4) * 1000);
        let target = -20;
        while (Date.now() < end && !signal.aborted) {
          simDevice.send(`K ${target}`);
          target = target === -20 ? 20 : -20;
          await sleep(2500, signal);
        }
        simDevice.send('K 0');
        break;
      }
    }
  } finally {
    simDevice.send('P0');
    simDevice.send('A12 0');
    useAppStore.getState().setSession({ runningProtocol: null, progressPct: 0, elapsedSec: 0 });
  }
}
```

**Step 3: Run tests**

```bash
npm run test
```

Expected: all pass.

**Step 4: Commit**

```bash
git add drx-simulator/web/src/sim
git commit -m "Add protocol runner with abort-controllable sequences"
```

---

### Task 5.2: Protocols page UI

**Files:**
- Modify: `drx-simulator/web/src/ui/pages/ProtocolsPage.tsx`

**Step 1: Write the page**

```tsx
import { useRef } from 'react';
import { PageShell } from './PageShell';
import { Card } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Slider } from '../../components/ui/slider';
import { useAppStore, type ProtocolId } from '../../store/useAppStore';
import { runProtocol } from '../../sim/protocolRunner';

const PROTOCOLS: Array<{ id: ProtocolId; label: string; desc: string }> = [
  { id: 1, label: 'Axial Only', desc: 'Pressure-only decompression' },
  { id: 2, label: 'Left Lateral', desc: 'Axial + left lateral rotation' },
  { id: 3, label: 'Right Lateral', desc: 'Axial + right lateral rotation' },
  { id: 4, label: 'Oscillating', desc: 'Continuous lateral sweep' },
];

export function ProtocolsPage() {
  const session = useAppStore((s) => s.session);
  const setSession = useAppStore((s) => s.setSession);
  const abortRef = useRef<AbortController | null>(null);

  const start = (id: ProtocolId) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    runProtocol(id, abortRef.current.signal, {
      durationSec: session.durationSec,
      maxPressure: session.maxPressure,
      usePulse: session.usePulse,
    });
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
  };

  return (
    <PageShell title="Protocols">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4 max-w-md">
          <div>
            <div className="text-sm text-white/60 mb-1">Max Pressure: {session.maxPressure} lbs</div>
            <Slider
              min={10} max={80} step={5}
              value={[session.maxPressure]}
              onValueChange={([v]) => setSession({ maxPressure: v })}
            />
          </div>
          <div>
            <div className="text-sm text-white/60 mb-1">Duration: {session.durationSec} s</div>
            <Slider
              min={10} max={120} step={5}
              value={[session.durationSec]}
              onValueChange={([v]) => setSession({ durationSec: v })}
            />
          </div>
        </div>

        <label className="flex items-center gap-2 text-white/80">
          <input
            type="checkbox"
            checked={session.usePulse}
            onChange={(e) => setSession({ usePulse: e.target.checked })}
          />
          Enable pulsing
        </label>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {PROTOCOLS.map((p) => (
            <Card
              key={p.id}
              className={`p-4 cursor-pointer transition ${
                session.runningProtocol === p.id
                  ? 'bg-blue-600/30 border-blue-400'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
              }`}
              onClick={() => (session.runningProtocol === p.id ? stop() : start(p.id))}
            >
              <div className="font-medium text-white">{p.label}</div>
              <div className="text-xs text-white/60 mt-1">{p.desc}</div>
              <Button variant="secondary" size="sm" className="mt-3 w-full">
                {session.runningProtocol === p.id ? 'Stop' : 'Start'}
              </Button>
            </Card>
          ))}
        </div>
      </div>
    </PageShell>
  );
}
```

**Step 2: Verify**

`npm run dev` > Protocols > click "Left Lateral" Start. Axial extends, pressure ramps, leg swings left and back. Card highlighted while running. Clicking Stop aborts.

**Step 3: Commit**

```bash
git add drx-simulator/web/src/ui
git commit -m "Add Protocols page with 4 protocol cards"
```

---

### Task 5.3: E-Stop latched banner

**Files:**
- Create: `drx-simulator/web/src/ui/EStopBanner.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Banner**

```tsx
import { useAppStore } from '../store/useAppStore';
import { Button } from '../components/ui/button';
import { simDevice } from '../sim/useSimTick';

export function EStopBanner() {
  const eStop = useAppStore((s) => s.device.eStop);
  if (!eStop) return null;

  return (
    <div className="absolute top-14 left-0 right-0 bg-red-600 text-white px-6 py-3 flex items-center justify-between pointer-events-auto z-10">
      <div className="font-medium">EMERGENCY STOP ENGAGED</div>
      <Button variant="outline" onClick={() => simDevice.resetEStop()}>Reset</Button>
    </div>
  );
}
```

**Step 2: Render in `App.tsx`**

```tsx
import { EStopBanner } from './ui/EStopBanner';

// in JSX:
<TopBar />
<EStopBanner />
<PageRouter />
<BottomNav />
```

**Step 3: Verify**

Click E-Stop → red banner, motion halts. Click Reset → clears.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add latched E-Stop banner"
```

---

### Task 5.4: Event log (command stream)

**Files:**
- Create: `drx-simulator/web/src/ui/EventLog.tsx`
- Modify: `drx-simulator/web/src/sim/SimulatedDevice.ts`
- Modify: `drx-simulator/web/src/store/useAppStore.ts`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Add log slice to store**

In `useAppStore.ts`, add to `AppState`:

```ts
logEntries: Array<{ t: number; msg: string }>;
pushLog: (msg: string) => void;
clearLog: () => void;
```

In the creator:

```ts
logEntries: [],
pushLog: (msg) => set((s) => ({
  logEntries: [...s.logEntries, { t: Date.now(), msg }].slice(-100),
})),
clearLog: () => set({ logEntries: [] }),
```

**Step 2: Push commands in `SimulatedDevice.ts`**

In `send()`, after `if (!parsed) return;`:

```ts
useAppStore.getState().pushLog(`>> ${raw}`);
```

**Step 3: `EventLog.tsx`**

```tsx
import { useAppStore } from '../store/useAppStore';
import { useEffect, useRef } from 'react';

export function EventLog() {
  const entries = useAppStore((s) => s.logEntries);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [entries]);

  return (
    <div
      ref={ref}
      className="absolute left-6 bottom-20 w-72 h-40 bg-black/60 backdrop-blur border border-white/10 rounded p-3 pointer-events-auto font-mono text-xs text-green-300 overflow-auto"
    >
      <div className="text-white/50 mb-2">Command Stream</div>
      {entries.map((e, i) => <div key={i}>{e.msg}</div>)}
    </div>
  );
}
```

**Step 4: Render in `App.tsx` (only on Setup/Protocols)**

```tsx
import { EventLog } from './ui/EventLog';

const page = useAppStore((s) => s.ui.page);

// in JSX:
{(page === 'setup' || page === 'protocols') && <EventLog />}
```

**Step 5: Verify**

Drag sliders on Setup → commands scroll in the log. Run a protocol — see the command stream.

**Step 6: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add event log panel showing live command stream"
```

---

### Task 5.5: Loading screen + self-test

**Files:**
- Create: `drx-simulator/web/src/ui/LoadingGate.tsx`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: `LoadingGate.tsx`**

```tsx
import { useProgress } from '@react-three/drei';
import { useEffect, useState } from 'react';

export function LoadingGate({ children }: { children: React.ReactNode }) {
  const { progress, active } = useProgress();
  const [webglOk, setWebglOk] = useState<boolean | null>(null);

  useEffect(() => {
    try {
      const c = document.createElement('canvas');
      setWebglOk(!!(c.getContext('webgl2') || c.getContext('webgl')));
    } catch {
      setWebglOk(false);
    }
  }, []);

  if (webglOk === false) {
    return (
      <div className="w-screen h-screen bg-black text-white flex items-center justify-center p-8 text-center">
        <div>
          <h1 className="text-2xl mb-2">Browser not supported</h1>
          <p className="text-white/60">Please use Chrome, Firefox, or Safari on a desktop.</p>
        </div>
      </div>
    );
  }

  return (
    <>
      {children}
      {active && (
        <div className="absolute inset-0 bg-black flex items-center justify-center z-50">
          <div className="text-white text-center">
            <div className="text-lg mb-3">Loading DRX Simulator...</div>
            <div className="w-64 h-1.5 bg-white/10 rounded overflow-hidden">
              <div className="h-full bg-blue-400 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <div className="text-xs text-white/40 mt-2">{Math.round(progress)}%</div>
          </div>
        </div>
      )}
    </>
  );
}
```

**Step 2: Wrap app**

```tsx
import { LoadingGate } from './ui/LoadingGate';

export default function App() {
  useSimTick();
  const page = useAppStore((s) => s.ui.page);
  return (
    <LoadingGate>
      <div className="relative w-screen h-screen bg-black">
        <Scene />
        <div className="absolute inset-0 pointer-events-none">
          <TopBar />
          <EStopBanner />
          <PageRouter />
          <BottomNav />
          {(page === 'setup' || page === 'protocols') && <EventLog />}
        </div>
      </div>
    </LoadingGate>
  );
}
```

**Step 3: Verify**

Hard-reload (Ctrl+Shift+R). Loading bar appears briefly.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add loading gate with progress bar and WebGL self-test"
```

---

### Task 5.6: Idle auto-demo

**Files:**
- Create: `drx-simulator/web/src/ui/useIdleDemo.ts`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Hook**

```ts
import { useEffect, useRef } from 'react';
import { useAppStore } from '../store/useAppStore';
import { runProtocol } from '../sim/protocolRunner';

const IDLE_MS = 30_000;

export function useIdleDemo() {
  const controllerRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    const reset = () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      controllerRef.current?.abort();
      timerRef.current = window.setTimeout(() => {
        const { session, device } = useAppStore.getState();
        if (session.runningProtocol || device.eStop) return;
        controllerRef.current = new AbortController();
        runProtocol(4, controllerRef.current.signal, {
          durationSec: 20,
          maxPressure: 40,
          usePulse: false,
        });
      }, IDLE_MS);
    };

    const events = ['mousemove', 'mousedown', 'keydown', 'touchstart'];
    events.forEach((e) => window.addEventListener(e, reset));
    reset();
    return () => {
      events.forEach((e) => window.removeEventListener(e, reset));
      if (timerRef.current) window.clearTimeout(timerRef.current);
      controllerRef.current?.abort();
    };
  }, []);
}
```

**Step 2: Call in `App.tsx`**

```tsx
import { useIdleDemo } from './ui/useIdleDemo';

export default function App() {
  useSimTick();
  useIdleDemo();
  // ...
}
```

**Step 3: Verify**

Load app, don't touch for 30s → protocol 4 auto-runs. Move mouse → cancels.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add idle auto-demo (protocol 4 after 30s inactivity)"
```

---

### Task 5.7: Keyboard shortcuts

**Files:**
- Create: `drx-simulator/web/src/ui/useKeyboardShortcuts.ts`
- Modify: `drx-simulator/web/src/App.tsx`

**Step 1: Hook**

```ts
import { useEffect, useRef } from 'react';
import { useAppStore } from '../store/useAppStore';
import { simDevice } from '../sim/useSimTick';
import { runProtocol } from '../sim/protocolRunner';
import type { ProtocolId } from '../store/useAppStore';

export function useKeyboardShortcuts() {
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      const s = useAppStore.getState();
      switch (e.key) {
        case ' ':
          e.preventDefault();
          simDevice.send('X');
          break;
        case '1':
        case '2':
        case '3':
        case '4': {
          controllerRef.current?.abort();
          controllerRef.current = new AbortController();
          runProtocol(Number(e.key) as ProtocolId, controllerRef.current.signal, {
            durationSec: s.session.durationSec,
            maxPressure: s.session.maxPressure,
            usePulse: s.session.usePulse,
          });
          break;
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
}
```

**Step 2: Call in `App.tsx`**

```tsx
import { useKeyboardShortcuts } from './ui/useKeyboardShortcuts';

export default function App() {
  useSimTick();
  useIdleDemo();
  useKeyboardShortcuts();
  // ...
}
```

**Step 3: Verify**

Press `2` — left lateral protocol runs. Press space — E-Stop.

**Step 4: Commit**

```bash
git add drx-simulator/web/src
git commit -m "Add keyboard shortcuts (1-4 protocols, space E-Stop)"
```

---

### Task 5.8: Deploy final version to Vercel

**Step 1: Push and deploy**

```bash
git push
```

Vercel auto-deploys from the connected branch. Or:

```bash
cd drx-simulator/web
npx vercel --prod
```

**Step 2: Smoke test production URL**

- Model loads within ~3s on good wifi.
- All 4 protocols run end-to-end.
- E-Stop latches and resets.
- Setup tabs drive actuators.
- No console errors.

**Step 3: Share URL** with sales/investor stakeholders.

---

## Coding Standards

- **TypeScript strict mode** — keep `"strict": true`; no `any` without a reason.
- **Component naming** — PascalCase for components (`DeviceModel.tsx`), camelCase for non-component modules (`parseCommand.ts`).
- **Imports** — relative within `src/`, no path aliases.
- **Styling** — Tailwind classes directly in JSX; no separate CSS except `index.css`.
- **State** — Zustand for app state; `useRef`/`useState` only for truly local UI state.
- **Testing** — vitest for `sim/` and `store/`. Skip component tests; `scene/`/`ui/` verified visually.
- **Commits** — one logical change per commit; test + impl in the same commit when added together.

## Definition of Done

- `npm run build` succeeds with no TypeScript or Vite errors.
- `npm run test` passes.
- Production Vercel deployment loads in under 5s on broadband.
- All 4 protocols run to completion without errors.
- E-Stop latches and resets correctly.
- Lighthouse Performance score at least 90 on the Vercel production URL.
