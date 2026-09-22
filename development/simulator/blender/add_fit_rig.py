"""Add FIT translation without rebuilding or altering the existing authored geometry.

The user confirmed that FIT slides the entire front support away from the chair.
Run in Blender, then export_model.py and validate_rig.py. Safe to rerun.
"""
from pathlib import Path

import bpy


def add_fit_rig() -> None:
    """Insert an identity parent so all existing pivots retain their rest pose."""
    working = bpy.data.collections["DRX working model"]
    if "fit_slider" not in bpy.data.objects:
        fit = bpy.data.objects.new("fit_slider", None)
        working.objects.link(fit)
        fit.parent = bpy.data.objects["static_frame"]
        fit.empty_display_type = "ARROWS"
        fit.empty_display_size = 0.15
        horizontal = bpy.data.objects["horizontal_pivot"]
        world = horizontal.matrix_world.copy()
        horizontal.parent = fit
        horizontal.matrix_world = world
    fit = bpy.data.objects["fit_slider"]
    fit["drxAxisLocal"] = [0.0, 0.0, 1.0]  # Exported glTF Y-up, forward from chair.
    fit["drxFidelity"] = "Confirmed assembly motion; unmeasured travel and linkage."
    for label, root_name in (
        ("fixed-chair", "Chair:1"),
        ("front-support", "Base extension:1"),
        ("leg-tray", "Traction tray:1"),
        ("traction-carriage", "Traction body:1"),
    ):
        root = bpy.data.objects[root_name]
        meshes = sorted(
            (obj for obj in (root, *root.children_recursive)
             if obj.type == "MESH" and not obj.hide_render),
            key=lambda obj: obj.name,
        )
        assert meshes, root_name
        meshes[0]["drxLandmark"] = label
    scene = bpy.context.scene
    scene["drxModelVersion"] = "2"
    scene["drxFitRepresentation"] = "Front support translates along chair's forward axis."
    notes = bpy.data.texts.get("READ ME - simulation rig")
    if notes:
        contents = notes.as_string().replace("The three named empties", "The four named empties")
        contents = contents.replace(
            "Leg-length/FIT is shown numerically until its mechanism is established.",
            "FIT translates the whole front support away from the fixed chair along +Z in glTF.\n"
            "Its travel remains an open-loop estimate; geometry is not a measured linkage.",
        )
        notes.clear()
        notes.write(contents)


if __name__ == "__main__":
    source = Path(__file__).resolve().parent / "drx.blend"
    bpy.ops.wm.open_mainfile(filepath=str(source))
    add_fit_rig()
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
