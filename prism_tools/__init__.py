"""Levels of Prism in Blender: see Tools/blender/README.md."""
import bpy

from . import engine, project, props, ui


def register():
    bpy.utils.register_class(project.PrismPreferences)
    props.register()
    ui.register()
    engine.register()


def unregister():
    engine.unregister()
    ui.unregister()
    props.unregister()
    bpy.utils.unregister_class(project.PrismPreferences)
