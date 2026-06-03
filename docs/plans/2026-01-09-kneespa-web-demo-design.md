# KneeSpa Web Demo - Design Document

**Date:** 2026-01-09
**Purpose:** Portfolio piece demonstrating the KneeSpa knee decompression therapy system
**Audience:** Potential employers/technical reviewers

---

## Overview

A web-based demo GUI that visualizes the KneeSpa device behavior without requiring hardware. Showcases frontend design, technical understanding of the system, and full-stack architecture patterns.

## File Structure

```
demo/
├── index.html          # Layout and structure
├── styles.css          # All styling and animations
├── js/
│   ├── app.js          # Main controller, UI event handling
│   ├── simulation.js   # KneeSpa device simulation logic
│   └── visualization.js # SVG knee diagram rendering/animation
└── assets/
    └── (optional SVG assets if needed)
```

## Architecture

Uses a simplified MVC pattern mirroring the real KneeSpa system:

- **Simulation (Model)** - `simulation.js` contains a `KneeSpaSimulator` class that mimics the Arduino communication. Maintains device state (pressure, lateral angle, protocol phase) and emits events when values change - just like the real `Arduino` class uses PyQt signals.

- **Visualization (View)** - `visualization.js` renders an SVG knee diagram that responds to state changes. The knee joint visually separates (axial), tilts (lateral), and pulses.

- **App Controller** - `app.js` wires everything together, handles button clicks, and updates gauge displays.

## Visual Layout

Two-panel layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  KneeSpa™ Decompression Therapy Simulator          [Portfolio] │
├────────────────────────────────┬────────────────────────────────┤
│                                │   PROTOCOL SELECT              │
│                                │   ┌───┐ ┌───┐ ┌───┐ ┌───┐     │
│      ┌─────────────────┐       │   │ 1 │ │ 2 │ │ 3 │ │ 4 │     │
│      │                 │       │   └───┘ └───┘ └───┘ └───┘     │
│      │   KNEE DIAGRAM  │       │   Axial  Left  Right  Osc     │
│      │                 │       ├────────────────────────────────┤
│      │  (SVG animated) │       │   GAUGES                       │
│      │                 │       │   ┌─────────┐  ┌─────────┐    │
│      │   Shows:        │       │   │Pressure │  │ Lateral │    │
│      │   - Joint gap   │       │   │  45 lbs │  │  -15°   │    │
│      │   - Tilt angle  │       │   └─────────┘  └─────────┘    │
│      │   - Pulse effect│       ├────────────────────────────────┤
│      └─────────────────┘       │   CONTROLS                     │
│                                │   [  START  ]  [ STOP ]        │
│      Status: "Ramping..."      │   ☑ Pulse Mode                 │
│      ████████░░ 75%            │                                │
│                                │   Protocol Duration: 0:34      │
└────────────────────────────────┴────────────────────────────────┘
```

### Left Panel (Visualization)
- SVG knee diagram showing femur/tibia bones with joint space
- Animates: vertical separation (pressure), rotation (lateral angle), pulsing glow effect
- Status text showing current phase ("Ramping pressure...", "Moving left...", "Pulsing...")
- Progress bar for protocol completion

### Right Panel (Controls)
- Protocol selector buttons (1-4) with labels
- Circular gauge for pressure (0-80 lbs) with animated needle
- Circular gauge for lateral angle (-20° to +20°)
- Start/Stop buttons styled like the real app (green/red)
- Pulse mode checkbox
- Elapsed time display

## Knee Visualization (SVG)

Simplified side-view schematic:

```
        ┌──────────┐
        │  FEMUR   │  (thigh bone - upper)
        │          │
        └────┬┬────┘
             ││ ←── Joint space (grows with pressure)
        ┌────┴┴────┐
        │  TIBIA   │  (shin bone - lower, tilts left/right)
        │          │
        └──────────┘
```

### Animation Behaviors

| Input | Visual Effect |
|-------|---------------|
| Pressure 0→80 lbs | Joint gap increases from 2px to 20px, bones separate vertically |
| Lateral -20° | Tibia rotates left, showing angle indicator arc |
| Lateral +20° | Tibia rotates right |
| Pulse ON | Gentle "breathing" animation - gap oscillates ±3px with glow effect |
| Protocol running | Subtle gradient/glow around active joint area |

### Visual Style
- Clean line art with slight drop shadows
- Color-coded: bones in light gray, joint space highlighted in therapeutic blue/teal
- Angle indicator arc shows current tilt degree
- Force arrows appear during pressure application

## Simulation Logic

### KneeSpaSimulator Class

```javascript
class KneeSpaSimulator extends EventEmitter {
  state = {
    pressure: 0,        // 0-80 lbs
    lateralAngle: 0,    // -20 to +20 degrees
    isPulsing: false,
    isRunning: false,
    protocol: null,     // 1, 2, 3, or 4
    phase: 'idle'       // 'idle', 'ramping', 'positioning', 'holding', 'pulsing', 'complete'
  }
}
```

### Protocol Sequences (accelerated ~10x)

| Protocol | Sequence |
|----------|----------|
| 1 - Axial | Ramp pressure 10→max (3s) → hold/pulse until duration |
| 2 - Left Lateral | Ramp pressure (3s) → move to left angle (1s) → hold/pulse |
| 3 - Right Lateral | Ramp pressure (3s) → move to right angle (1s) → hold/pulse |
| 4 - Oscillating | Ramp pressure (3s) → alternate left↔right every 3s while pulsing |

### Event Emissions

Mirrors the Arduino's PyQt signals:
- `status` → `{ pressure, lateralAngle, phase }` (every 100ms during operation)
- `phaseChange` → `{ phase, message }` (when transitioning)
- `complete` → protocol finished
- `stopped` → user cancelled

## Styling

### Colors
- Background: Clean white (`#ffffff`)
- Accent: Medical teal/blue (`#3498db`) for active states
- Start button: Green (`#00c800`) matching real app
- Stop button: Red (`#c80000`) matching real app
- Dark header: `rgb(30, 30, 30)` from existing UI

### Gauges
- Circular SVG gauges with animated needle rotation
- Pressure gauge: green→yellow→red gradient approaching max
- Lateral gauge: center-zero with left/right indicators

### Responsive
- Desktop (1200px+): full two-panel layout
- Tablet (768px+): slightly compressed
- Mobile: single column stack

## Portfolio Touches

- "View Source" link to GitHub
- "Built with vanilla JS - no frameworks" badge
- Clean console logs showing event flow
- Code comments explaining mapping to real system

## Timing

All animations accelerated ~10x from real device:
- Pressure ramp: ~3 seconds (real: 30+ seconds)
- Position change: ~1 second (real: 5+ seconds)
- Full protocol demo: 30-60 seconds (real: minutes)
