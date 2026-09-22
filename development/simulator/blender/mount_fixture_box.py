"""Center the black box inside the traction cage and attach it to its slider.

Run against the editable source, then export_model.py and validate_rig.py.
The correction is also called by the initial model builder.
"""
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def mount_fixture_box() -> None:
    """Keep the box's existing size, centered inside and fixed to the moving cage."""
    cover = bpy.data.objects["axial_rail_sleeve"]
    slider = bpy.data.objects["axial_slider"]
    frame = bpy.data.objects["lateral_pivot"]
    body = bpy.data.objects["Traction body:1"]
    bpy.context.view_layer.update()
    inverse = frame.matrix_world.inverted()
    points = [inverse @ obj.matrix_world @ vertex.co
              for obj in (body, *body.children_recursive)
              if obj.type == "MESH" and not obj.hide_render
              for vertex in obj.data.vertices]
    x, y, z = slider["drxAxisLocal"]
    forward = Vector((x, -z, y)).normalized()
    right = Vector((1, 0, 0))
    up = right.cross(forward).normalized()
    if up.z < 0:
        up.negate()
    center = Vector()
    for axis in (right, forward):
        projections = [point.dot(axis) for point in points]
        center += axis * (min(projections) + max(projections)) * 0.5
    dimensions = (0.16, 0.32, 0.08)
    heights = [point.dot(up) for point in points]
    center += up * (min(heights) + max(heights)) * 0.5
    rotation = Vector((0, 1, 0)).rotation_difference(forward)
    world = (frame.matrix_world @ Matrix.Translation(center)
             @ rotation.to_matrix().to_4x4() @ Matrix.Diagonal((*dimensions, 1)))
    cover.parent = slider
    cover.matrix_parent_inverse.identity()
    cover.matrix_world = world
    cover["drxLandmark"] = "fixture-box"
    cover["drxFidelity"] = "Centered inside moving cage per device owner."
    bpy.context.scene["drxModelVersion"] = "4"
    notes = bpy.data.texts.get("READ ME - simulation rig")
    old_note = "The black fixture box is centered below the traction body and moves with axial_slider."
    note = "The black fixture box is centered inside the traction cage and moves with axial_slider."
    if notes:
        contents = notes.as_string().replace(old_note, note)
        if note not in contents:
            contents += "\n" + note + "\n"
        notes.clear()
        notes.write(contents)
    bpy.context.view_layer.update()


if __name__ == "__main__":
    source = Path(__file__).resolve().parent / "drx.blend"
    bpy.ops.wm.open_mainfile(filepath=str(source))
    mount_fixture_box()
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
