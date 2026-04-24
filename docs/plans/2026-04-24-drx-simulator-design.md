# DRX Simulator — Design Document

**Date:** 2026-04-24
**Purpose:** Browser-based 3D simulator of the DRX device for sales demos and investor showpieces
**Audience:** Prospects, investors, and non-technical stakeholders who need to see and interact with the product without physical hardware

---

## Goals and Non-Goals

### Goals
- Recreate the clinician console (from `main/ui/guis/kneespa.ui`) as a web UI floating over a 3D model of the device.
- Let the viewer run all four treatment protocols (axial, left lateral, right lateral, oscillating) and watch the device respond.
- Let the viewer drive individual actuators manually via the Setup page sliders/buttons, matching the real UI.
- Ship as a static site deployable to Vercel with zero backend.
- Be bulletproof on demo day: offline-capable after load, fast first paint, kiosk-friendly auto-idle.

### Non-Goals
- Real hardware connectivity (no serial bridge, no WebSocket to a live device).
- Full fidelity of every page in the real PyQt app (Login/Help/Video are minimal stubs).
- Patient data flow, session history, video training library.
- Accessibility polish beyond basic keyboard nav and contrast.
- Behavioral parity with the real firmware down to timing (protocols are compressed ~10× for demo pacing).

---

## Top-Level Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Use case | Sales + investor demo | Optimize for "wow in 10 seconds" and reliability over training accuracy |
| UI aesthetic | Mirror the real clinician console | Credibility — viewer sees what clinicians actually use |
| Scope | Full shell: bottom nav + functional Protocols + functional Setup + stub Home/Login/Help/Video | Middle ground: feels like the real product without weeks of stub work |
| Tech stack | Vite + React + TypeScript + react-three-fiber + Tailwind + shadcn/ui + Zustand | Right hammer for multi-page UI with live 3D state |
| Hosting | Vercel static deployment from `web/` | One-command deploy, preview URL on every push |
| 3D source | Existing STEP files, converted to GLB via Blender | CAD-accurate geometry, part-separated for animation |

---

## Architecture

### Repository Layout

```
drx-simulator/
├── STEP Files/                    # source CAD, unchanged
├── drx-body-imgs/                 # reference renders, unchanged
└── web/                           # Vite+React app; this is what Vercel deploys
    ├── public/
    │   └── models/
    │       └── drx.glb            # built artifact, checked in
    ├── scripts/
    │   └── step-to-glb.md         # documented conversion process
    ├── src/
    │   ├── scene/                 # R3F scene: rigging, lights, camera, device model
    │   ├── ui/                    # clinician console: shell, pages, controls
    │   ├── sim/                   # simulated actuators + protocol runners (pure TS)
    │   ├── store/                 # Zustand slices
    │   ├── App.tsx
    │   └── main.tsx
    ├── index.html
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── vite.config.ts
    └── vercel.json
```

### Layer Separation

Three layers with strict one-way data flow:

```
sim/ (pure TS)  ──writes──▶  store/ (Zustand)  ──reads──▶  scene/ + ui/
     ▲                                                        │
     └──────────────── commands via sim.send() ◀──────────────┘
```

- `sim/` is the device model. No React, no three.js, no DOM. Pure TypeScript classes and functions. Unit-testable with vitest.
- `store/` is the single source of truth for live state. Device positions, session flags, UI state.
- `scene/` renders 3D transforms by subscribing to the store.
- `ui/` renders the clinician console by subscribing to the store and calls `sim.send()` to issue commands.

This mirrors the real Python app's separation (`Arduino` class ↔ `Protocols` ↔ `KneeSpa` UI) and keeps the sim logic testable without a browser.

---

## The Device Model

### Actuator Ranges (from `main/config/constants.py`)

| Actuator | Range | Command prefix | 3D transform |
|---|---|---|---|
| Axial (A12) | 0 – 4 in | `A12 <value>` | Translate `axial_slider` along local Z |
| Horizontal (B) | -25° to +5° | `B<value>` | Rotate `horizontal_pivot` around X |
| Lateral (K) | -20° to +20° | `K <value>` | Rotate `lateral_pivot` around Y |
| Pressure (P) | 0 – 80 lbs | `P<value>` | Visual only: emissive glow intensity on strap material |

### Simulated Device State

```ts
type DeviceState = {
  axial:      { pos: number; target: number; moving: boolean };
  horizontal: { pos: number; target: number; moving: boolean };
  lateral:    { pos: number; target: number; moving: boolean };
  pressure:   { lbs: number; target: number };
  pulsing:    boolean;
  eStop:      boolean;
};
```

### Motion Model

Each actuator eases toward its target using `requestAnimationFrame`-driven ticks with a cosine ease-out profile. Speeds (demo-tuned, not real-device-matched):

- Axial: ~1 in/sec
- Horizontal, Lateral: ~30°/sec
- Pressure ramp: ~20 lbs/sec

### Simulated Device API

`SimulatedDevice` mirrors the `Arduino` class surface. Command strings match real firmware vocabulary:

| Command | Effect |
|---|---|
| `A12 <in>` | Set axial target |
| `B<deg>` | Set horizontal target |
| `K <deg>` | Set lateral target |
| `P<lbs>` | Set pressure target |
| `J` / `JS` | Start/stop pulsing |
| `X` | Emergency stop (latches) |
| `T` | Keepalive; responds `OK` |

---

## 3D Scene

### Model Pipeline (STEP → GLB)

One-time conversion, re-run only when CAD changes. Documented in `web/scripts/step-to-glb.md`.

1. Import `Full assembly.stp` into Blender 4.2+ (built-in STEP importer).
2. Organize parts into 4 transform groups:
   - `static_frame` — Chair Frame, Casters, Electrical box, Handles, Base housing
   - `horizontal_pivot` (child of static_frame) — hinge origin at base-housing pivot
   - `lateral_pivot` (child of horizontal_pivot) — origin at Hinge (Lateral) part
   - `axial_slider` (child of lateral_pivot) — Traction body, Traction tray, Bent leg, Base extension
3. Bake simple PBR materials (matte grey, brushed metal, blue plastic) matching the reference renders.
4. Apply decimate modifier targeting ~100k–200k triangles total.
5. Export as `drx.glb` with Draco compression. Target < 5 MB.
6. Commit GLB to `web/public/models/`.

### Runtime Loading

`useGLTF('/models/drx.glb')` from `@react-three/drei`. Walk the scene with `scene.getObjectByName()` to get refs to the four transform groups, then drive transforms in `useFrame` from the Zustand store (bypassing React re-renders for smoothness).

### Lighting and Camera

- Environment lighting via `@react-three/drei` `<Environment preset="studio" />`.
- One subtle directional key light for shadow.
- OrbitControls enabled when idle, locked during protocol runs.
- Three preset camera angles as buttons: Overhead, Side, 3/4 View. Smooth lerps between them.

### Pressure Visualization

No geometry deformation. A custom emissive shader on the strap/bent-leg materials fades in red glow intensity with pressure. A floating HUD arrow near the leg pulses in size with pressure. Sells force without faking a deformable belt.

---

## UI — Clinician Console

### Layout

Full-viewport canvas as background. UI chrome floats on top as semi-transparent panels.

```
┌─────────────────────────────────────────────────┐
│  [ DRX Simulator ]              [ 🔴 E-STOP ]   │ ← top bar, always visible
│                                                 │
│         ╔═══════════════════════════╗          │
│         ║                           ║          │
│         ║    3D DEVICE (canvas)     ║          │
│         ║                           ║          │
│         ╚═══════════════════════════╝          │
│                                                 │
│  ┌───────── page content panel ──────────┐     │
│  │  (Home / Setup / Protocols / ...)      │    │
│  └────────────────────────────────────────┘    │
│                                                 │
│ [Login] [Setup] [Protocols] [Help] [▶ Video]   │ ← bottom nav
└─────────────────────────────────────────────────┘
```

### Pages

| Page | Fidelity | Contents |
|---|---|---|
| Home | Stub | Title, logo, "Welcome" blurb |
| Login | Stub | Static form; "Sign In" advances without validation |
| Setup | Full | Tabs per actuator (Axial, Horizontal, Lateral): forward/reverse + fast buttons, position slider + Go/Stop, pressure slider + Go/Stop — all wired to the sim |
| Protocols | Full | 4 protocol cards, Start button, pressure-max slider, duration input, pulse toggle; running shows progress ring + live position/pressure readout |
| Help | Stub | Static "see manual" content |
| Video | Stub | Modal with static image — "training video library" |

### Routing

Client-side. Bottom-nav buttons write to a Zustand `currentPage` key. No React Router.

### E-Stop

Always-visible red button, top-right. Click → `sim.send('X')`:
- All `moving` flags cleared
- Pressure ramps to 0 over 500 ms
- Latched red banner appears
- "Reset" button clears the latch

---

## Protocol Behaviors

All protocols start with the axial ramping out to ~3 in while pressure ramps 0 → target over ~3 s (demo-compressed from the real ~60 s ramp).

| Protocol | Sequence |
|---|---|
| 1 — Axial only | Ramp → hold. If pulse toggled, axial oscillates ±0.2 in at ~1 Hz and pressure meter pulses. Ends: pressure to 0, axial retracts. |
| 2 — Left lateral | Ramp → lateral rotates 0° → −20° over ~2 s → holds ~5 s → returns to 0°. |
| 3 — Right lateral | Same as protocol 2 but +20°. |
| 4 — Oscillating | Ramp → lateral sweeps −20° → +20° continuously until duration ends. |

### Protocol Runner

`sim/protocolRunner.ts` — async state machine. Each protocol is a sequence of `await stepTo(actuator, value, duration)` calls. Cancellable via `AbortController` (E-Stop and "Stop" button).

---

## State Management

### Zustand Slices

- **deviceSlice** — live actuator positions, targets, pulsing, eStop (written by sim, read by scene + UI)
- **sessionSlice** — current protocol id, elapsed time, progress %, duration, max pressure, use-pulse toggle
- **uiSlice** — current page, current setup tab, modal open flags

### Why Zustand

The sim ticks at 60 fps. Zustand's selector subscriptions mean UI panels only re-render on slices they subscribe to. The 3D scene reads directly from `getState()` in `useFrame`, triggering zero React re-renders. Smooth on a modest laptop at a pitch meeting.

---

## Demo-Day Reliability

Built into the app, not ad-hoc:

- **Offline-capable after load.** No fetch calls, no API keys. Works on bad wifi or airplane mode.
- **Loading state.** Full-screen spinner with progress bar for GLB download (drei `<Progress>`).
- **Auto-idle demo.** If no interaction for 30 s, run protocol 4 for 20 s, then return to idle.
- **Self-test on load.** Verify GLB loaded, pivot groups found, WebGL supported. On failure, show a friendly "please use Chrome/Firefox on desktop" screen.
- **Keyboard shortcuts.** `?` opens cheatsheet; arrows manually move actuators; `1–4` run protocols; `space` E-Stop.
- **Perf budget.** Lighthouse Performance ≥ 90. Main tax is GLB size; decimation handles it.

---

## Out of Scope

- Serial bridge or backend of any kind
- Real authentication
- Video library content
- Multi-language, full a11y, analytics
- Mobile-first design (desktop/tablet primary; mobile works but not optimized)

---

## Build Sequence

Five incremental chunks, each independently shippable to Vercel.

1. **Bootstrap + model pipeline** — Vite/React/Tailwind scaffold; STEP→GLB conversion; bare canvas renders the model with orbit controls.
2. **Sim core + store** — `SimulatedDevice` class, Zustand slices, vitest unit tests for command parsing and easing.
3. **Scene rigging** — wire store → transforms, easing, pressure glow shader, camera presets.
4. **UI shell + Setup page** — bottom nav, stub pages, full Setup with actuator tabs wired to sim.
5. **Protocols page + polish** — protocol runner, progress ring, event log, E-Stop, idle auto-demo, loading screen, self-test.

Rough estimate: ~7–8 focused days of work from scratch; faster with AI assistance.

---

## Open Questions

None blocking. To be resolved during implementation:

- Exact triangle count after decimation (visual-quality vs. load-time trade-off — iterate on the first Blender pass)
- Pivot-axis alignment in the STEP file (may need empty-parent wrappers if CAD origins aren't axis-aligned; trivial to fix)
- Whether to include the event log panel (command stream scrolling) in v1 or v1.1 — recommended v1, easy to cut if time-constrained
