"""Create the editable Blender source from the supplied CAD-derived GLB.

Run with Blender --background --factory-startup --python <this file>.
Subsequent manual edits should use export_model.py, not rerun this initial build.
"""
import json
import runpy
import sys
from pathlib import Path

import bpy
from mathutils import Vector


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = 1.0
bpy.ops.import_scene.gltf(filepath=str(HERE / "source.glb"))
working = bpy.data.collections.new("DRX working model")
bpy.context.scene.collection.children.link(working)
original_objects = list(bpy.data.objects)
for obj in original_objects:
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    working.objects.link(obj)

# Retain an untouched, hidden reference hierarchy inside the editable source.
reference = bpy.data.collections.new("Reference - original GLB")
bpy.context.scene.collection.children.link(reference)
copies = {}
for obj in original_objects:
    duplicate = obj.copy()
    duplicate.name = "REF__" + obj.name
    reference.objects.link(duplicate)
    copies[obj] = duplicate
for obj, duplicate in copies.items():
    duplicate.parent = copies.get(obj.parent)
reference.hide_render = True
reference.hide_viewport = True

axial = bpy.data.objects["axial_slider"]
raw = Vector(axial["drxAxisLocal"])
aligned = Vector((0, raw.y, raw.z)).normalized()
raw_blender = Vector((raw.x, -raw.z, raw.y)).normalized()
aligned_blender = Vector((aligned.x, -aligned.z, aligned.y))
correction = raw_blender.rotation_difference(aligned_blender)
for obj in (axial, bpy.data.objects["Traction tray:1"]):
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = correction @ obj.rotation_quaternion
axial["drxAxisLocal"] = list(aligned)
axial["drxAlignmentNote"] = "CAD rail side-pitch correction migrated from supplied viewer."

hide_prefixes = ("Hex Cap Screw", "Circular Washer", "Prevailing Torque", "Handle bushing")
for obj in original_objects:
    if obj.name == "Handle 3:1" or obj.name.startswith(hide_prefixes):
        for hidden in (obj, *obj.children_recursive):
            hidden.hide_render = True
            hidden.hide_set(True)
            hidden["drxExport"] = False

# Create the fixture box; mount_fixture_box below positions and parents it.
bpy.ops.mesh.primitive_cube_add(size=1)
cover = bpy.context.object
cover.name = "axial_rail_sleeve"
for collection in list(cover.users_collection):
    collection.objects.unlink(cover)
working.objects.link(cover)
cover.parent = bpy.data.objects["lateral_pivot"]
normal = Vector((0, 0, 1))
normal = (normal - aligned_blender * normal.dot(aligned_blender)).normalized()
cover.location = axial.location + aligned_blender * 0.045 + normal * 0.035
cover.rotation_mode = "QUATERNION"
cover.rotation_quaternion = Vector((0, 1, 0)).rotation_difference(aligned_blender)
cover.scale = (0.16, 0.32, 0.08)
material = bpy.data.materials.new("Rail sleeve - matte black")
material.diffuse_color = (0.008, 0.01, 0.009, 1)
material.use_nodes = True
material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = material.diffuse_color
material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.75
cover.data.materials.append(material)
cover["drxFidelity"] = "Illustrative sleeve; dimensions inherited from supplied viewer."

scene = bpy.context.scene
scene["drxModelVersion"] = "1"
scene["drxUnits"] = "meters"
scene["drxFidelity"] = "CAD-derived synthetic fixture; pivots/dimensions require measurement."
scene["drxFitRepresentation"] = "Viewer indicator only; FIT linkage dimensions not supplied."
scene["drxCoordinateConvention"] = "Patient left negative, right positive; glTF Y-up export."
notes = bpy.data.texts.new("READ ME - simulation rig")
notes.write("""DRX simulation model

The working collection is editable; the hidden reference retains the original GLB.
The three named empties are the runtime control contract. Their drxAxisLocal
properties are vectors in EXPORTED glTF coordinates (not Blender Z-up).
Horizontal and lateral angles are applied with negative sign in the viewer.
Axial displacement uses drxAxisLocal in meters, from the authored rest pose.
The source CAD dimensions and physical pivot locations have not been measured.
Leg-length/FIT is shown numerically until its mechanism is established.
The original viewer's axial side-pitch correction is baked here; never apply it again.
Use export_model.py to update the GLB and rig manifest after editing.
""")
from add_fit_rig import add_fit_rig
from mount_fixture_box import mount_fixture_box

add_fit_rig()
mount_fixture_box()
bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "drx.blend"))
runpy.run_path(str(HERE / "export_model.py"), run_name="__main__")
print("BLENDER_SOURCE_CREATED", json.dumps({"objects": len(original_objects),
                                            "source": str(HERE / "drx.blend")}))
