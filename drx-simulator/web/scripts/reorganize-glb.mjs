// Reorganizes the raw cascadio-converted GLB into four named pivot groups that
// the scene/ code expects: static_frame, horizontal_pivot, lateral_pivot,
// axial_slider. Preserves each part's world position by offsetting local
// translations relative to the new parent's world position.
//
// Run: node scripts/reorganize-glb.mjs

import { NodeIO } from '@gltf-transform/core';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = resolve(__dirname, '..');
const IN_PATH = resolve(WEB_ROOT, 'public/models/drx-raw.glb');
const OUT_PATH = resolve(WEB_ROOT, 'public/models/drx.glb');

// Which top-level part names belong to each moving group.
// Every other child becomes static frame.
const HORIZONTAL_PARTS = ['Base extension:1'];
const LATERAL_PARTS = ['Hinge:1'];
const AXIAL_PARTS = ['Traction body:1', 'Traction tray:1'];

const io = new NodeIO();
const doc = await io.read(IN_PATH);
const root = doc.getRoot();
const scene = root.listScenes()[0];

const assembly = scene.listChildren()[0];
if (!assembly || assembly.getName() !== 'Full assembly') {
  throw new Error('Expected top-level "Full assembly" node; got: ' + assembly?.getName());
}

const byName = new Map();
for (const c of assembly.listChildren()) byName.set(c.getName(), c);

function req(name) {
  const n = byName.get(name);
  if (!n) throw new Error('Missing part in GLB: ' + name);
  return n;
}

const horizontalWorld = req('Base extension:1').getTranslation();
const lateralWorld = req('Hinge:1').getTranslation();
const axialWorld = req('Traction tray:1').getTranslation();

function sub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

const staticFrame = doc.createNode('static_frame');

const horizontalPivot = doc.createNode('horizontal_pivot');
horizontalPivot.setTranslation(horizontalWorld);

const lateralPivot = doc.createNode('lateral_pivot');
lateralPivot.setTranslation(sub(lateralWorld, horizontalWorld));

const axialSlider = doc.createNode('axial_slider');
axialSlider.setTranslation(sub(axialWorld, lateralWorld));

horizontalPivot.addChild(lateralPivot);
lateralPivot.addChild(axialSlider);
staticFrame.addChild(horizontalPivot);

function reparentPreservingWorld(child, newParent, parentWorld) {
  const t = child.getTranslation();
  child.setTranslation(sub(t, parentWorld));
  newParent.addChild(child);
}

const originalChildren = [...assembly.listChildren()];
const counts = { static: 0, horizontal: 0, lateral: 0, axial: 0 };

for (const child of originalChildren) {
  const name = child.getName();
  if (HORIZONTAL_PARTS.includes(name)) {
    reparentPreservingWorld(child, horizontalPivot, horizontalWorld);
    counts.horizontal++;
  } else if (LATERAL_PARTS.includes(name)) {
    reparentPreservingWorld(child, lateralPivot, lateralWorld);
    counts.lateral++;
  } else if (AXIAL_PARTS.includes(name)) {
    reparentPreservingWorld(child, axialSlider, axialWorld);
    counts.axial++;
  } else {
    staticFrame.addChild(child);
    counts.static++;
  }
}

scene.addChild(staticFrame);
scene.removeChild(assembly);
assembly.dispose();

await io.write(OUT_PATH, doc);

console.log('Reorganized:', counts);
console.log('Wrote', OUT_PATH);
