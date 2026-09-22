"""Check the authored rig and save independent Blender landmark reference poses.

Run after export: blender --background --factory-startup --python <this file>.
These validate coordinate/parenting consistency, not measured device geometry.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parent / "viewer/public/models"
bpy.ops.wm.open_mainfile(filepath=str(HERE / "drx.blend"))
rig = json.loads((OUTPUT / "rig.json").read_text(encoding="utf-8"))
assert rig["model_sha256"] == hashlib.sha256((OUTPUT / "drx.glb").read_bytes()).hexdigest()
names = ("static_frame", "fit_slider", "horizontal_pivot", "lateral_pivot", "axial_slider")
nodes = {name: bpy.data.objects[name] for name in names}
for parent, child in zip(names, names[1:]):
    assert nodes[child].parent == nodes[parent], (child, "wrong parent")
for joint in rig["joints"].values():
    assert abs(sum(x * x for x in joint["axis"]) - 1) < 1e-6
assert rig["joints"]["lateral"]["sign"] == -1
assert rig["joints"]["horizontal"]["sign"] == -1
assert abs(rig["joints"]["axial"]["axis"][0]) < 1e-6
bases = {name: (node.location.copy(), node.rotation_quaternion.copy())
         for name, node in nodes.items()}
poses = [
    ("neutral", 0, 0, 0, 0), ("axial-full", 4, 0, 0, 0),
    ("patient-left", 0, 0, -20, 0), ("patient-right", 0, 0, 20, 0),
    ("horizontal-low", 0, -25, 0, 0), ("horizontal-high", 0, 5, 0, 0),
    ("combined-left", 4, -25, -20, 6), ("combined-right", 4, 5, 20, 6),
    ("fit-full", 0, 0, 0, 6), ("fit-middle", 0, 0, 0, 3),
]
meshes = {obj["drxLandmark"]: obj
          for obj in bpy.data.collections["DRX working model"].all_objects
          if obj.type == "MESH" and obj.get("drxLandmark")}
assert len(meshes) == 5
assert meshes["fixture-box"].parent == nodes["axial_slider"]
references = []
for label, axial, horizontal, lateral, fit in poses:
    for key, value in (("fit", fit), ("axial", axial),
                       ("horizontal", horizontal), ("lateral", lateral)):
        joint = rig["joints"][key]
        obj = nodes[joint["node"]]
        location, rotation = bases[obj.name]
        x, y, z = joint["axis"]
        axis = Vector((x, -z, y))
        obj.location = location
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = rotation
        if key in ("axial", "fit"):
            obj.location = location + axis * value * 0.0254
        else:
            obj.rotation_quaternion = Quaternion(axis, math.radians(value) * joint["sign"]) @ rotation
    bpy.context.view_layer.update()
    # The fixed local probe, beyond the slider pivot, reveals both rotations
    # and translations. It is also evaluated independently by Three.js tests.
    points = {}
    for name in names:
        point = nodes[name].matrix_world @ Vector((0, -0.2, 0))
        points[name] = [point.x, point.z, -point.y]
    mesh_points = {}
    for label_key, mesh in meshes.items():
        local = mesh.data.vertices[0].co
        point = mesh.matrix_world @ local
        mesh_points[label_key] = {"local": [local.x, local.z, -local.y],
                                  "world": [point.x, point.z, -point.y]}
    references.append({"name": label, "pose": {
        "axial_inches": axial, "horizontal_degrees": horizontal,
        "lateral_degrees": lateral, "fit_inches": fit},
        "landmarks": points, "mesh_landmarks": mesh_points})
neutral, full, left, right, low, high = references[:6]
point = lambda pose: Vector(pose["landmarks"]["axial_slider"])
assert abs((point(full) - point(neutral)).length - 0.1016) < 1e-6
assert point(left).x > point(neutral).x > point(right).x
assert point(high).y > point(neutral).y > point(low).y
for pose in references:
    assert pose["landmarks"]["static_frame"] == neutral["landmarks"]["static_frame"]
    assert (pose["mesh_landmarks"]["fixed-chair"]
            == neutral["mesh_landmarks"]["fixed-chair"])
assert abs((point(references[8]) - point(neutral)).length - 0.1524) < 1e-6
payload = {"schema": 1, "model_sha256": rig["model_sha256"],
           "probe_gltf": [0, 0, 0.2], "poses": references,
           "scope": "Blender/Three transform consistency; no physical measurements"}
(OUTPUT / "reference-poses.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("RIG_VALIDATION_PASSED", len(references), "poses")
