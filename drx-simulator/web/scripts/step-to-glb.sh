#!/usr/bin/env bash
# Converts the DRX STEP assembly to the final animation-ready GLB.
# Requires: python3 with cascadio (auto-installed into .venv), node + gltf-transform.
#
# Run from drx-simulator/web/:  ./scripts/step-to-glb.sh

set -euo pipefail

WEB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$WEB_DIR/../.." && pwd)"
STEP_FILE="$REPO_ROOT/drx-simulator/STEP Files/Full assembly.stp"
VENV="$WEB_DIR/.venv-cad"
RAW_GLB="$WEB_DIR/public/models/drx-raw.glb"
OUT_GLB="$WEB_DIR/public/models/drx.glb"

mkdir -p "$WEB_DIR/public/models"

if [ ! -d "$VENV" ]; then
  echo "Creating Python venv for cascadio..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet cascadio
fi

echo "[1/2] STEP -> GLB (cascadio)"
"$VENV/bin/python" -c "
import cascadio
code = cascadio.step_to_glb(
    '$STEP_FILE',
    '$RAW_GLB',
    tol_linear=0.5,
    tol_angular=1.0,
    merge_primitives=False,
)
assert code == 0, f'cascadio returned {code}'
"

echo "[2/2] Reorganize into named pivot groups (gltf-transform)"
node "$WEB_DIR/scripts/reorganize-glb.mjs"

rm -f "$RAW_GLB"
echo "Done: $OUT_GLB ($(du -h "$OUT_GLB" | cut -f1))"
