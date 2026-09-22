"""Export the selected working rig and its inspectable manifest from drx.blend."""
import hashlib
import json
import math
from pathlib import Path

import bpy


HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parent / "viewer/public/models"
if "DRX working model" not in bpy.data.collections:
    bpy.ops.wm.open_mainfile(filepath=str(HERE / "drx.blend"))
bpy.ops.object.select_all(action="DESELECT")
for obj in bpy.data.collections["DRX working model"].all_objects:
    if obj.get("drxExport", True) and not obj.hide_render:
        obj.hide_set(False)
        obj.select_set(True)

joints = {}
for key, name, sign in (("fit", "fit_slider", 1),
                        ("axial", "axial_slider", 1),
                        ("horizontal", "horizontal_pivot", -1),
                        ("lateral", "lateral_pivot", -1)):
    obj = bpy.data.objects[name]
    axis = list(obj["drxAxisLocal"])
    length = math.sqrt(sum(value * value for value in axis))
    if not math.isfinite(length) or length < 0.99:
        raise ValueError("Invalid joint axis: " + name)
    joints[key] = {"node": name, "axis": [value / length for value in axis], "sign": sign}
OUTPUT.mkdir(parents=True, exist_ok=True)
glb = OUTPUT / "drx.glb"
bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True,
                          export_extras=True, export_yup=True, export_animations=False)
manifest = {"schema": 1, "model_sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
            "units": "meters", "coordinate_frame": "glTF Y-up",
            "patient_lateral": "negative=left, positive=right", "joints": joints,
            "fidelity": "CAD-derived geometry; unmeasured synthetic mechanism",
            "fit": "Front leg-support assembly slides away from chair; travel is estimated",
            "source_blender": bpy.app.version_string,
            "source_sha256": hashlib.sha256((HERE / "source.glb").read_bytes()).hexdigest()}
(OUTPUT / "rig.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("EXPORTED_MODEL", manifest["model_sha256"])
