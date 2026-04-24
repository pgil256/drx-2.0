# STEP → GLB Conversion

Generates `public/models/drx.glb` from `drx-simulator/STEP Files/Full assembly.stp`.

One-time. Re-run only when CAD changes.

## Quick path (headless, CI-friendly)

```bash
cd drx-simulator/web
./scripts/step-to-glb.sh
```

This is the path used in this repo. It:

1. Creates a local Python venv (`.venv-cad/`) and installs `cascadio`, a pybind11 wrapper around OpenCascade that does STEP → GLB directly.
2. Converts the assembly to `drx-raw.glb`, preserving the STEP product hierarchy as glTF nodes (so each named part becomes its own node).
3. Runs `scripts/reorganize-glb.mjs` to reparent the top-level parts into four named groups that the runtime animation rigging expects:
   - `static_frame` — chair frame, handles, casters, base housing, electrical box, screws, washers
   - `horizontal_pivot` — `Base extension` (plus `lateral_pivot` nested inside it)
   - `lateral_pivot` — `Hinge` (plus `axial_slider` nested inside it)
   - `axial_slider` — `Traction body`, `Traction tray`
4. Positions each pivot node at the world location of its hinge geometry, adjusting children's local translations so world positions are preserved. This makes rotations happen around the correct axes.
5. Deletes the intermediate `drx-raw.glb`.

Output: `public/models/drx.glb`, ~2 MB.

## Requirements
- Python 3.10+
- Node.js 20+
- `@gltf-transform/core` (already a dev dep via `npm install --no-save` inside the script)

## Alternate path (Blender, for manual tuning)

If you need to tweak materials, decimation, or pivot placement interactively:

1. Open `Full assembly.stp` in Blender 4.2+ (built-in STEP importer).
2. Organize the Outliner into four empties: `static_frame`, `horizontal_pivot`, `lateral_pivot`, `axial_slider`. Parent them in that nesting order.
3. Place each empty at its hinge axis; parent the appropriate parts under each.
4. Export as glTF 2.0 (`.glb`) with Draco compression (level 6), +Y Up ON, Apply Modifiers ON, to `public/models/drx.glb`.

## Verification

After conversion, the app must resolve each pivot group:

```js
scene.getObjectByName('static_frame');
scene.getObjectByName('horizontal_pivot');
scene.getObjectByName('lateral_pivot');
scene.getObjectByName('axial_slider');
```

If any return `undefined`, re-run the reorganizer or check that node names in the raw GLB still match `HORIZONTAL_PARTS` / `LATERAL_PARTS` / `AXIAL_PARTS` in `reorganize-glb.mjs`.
