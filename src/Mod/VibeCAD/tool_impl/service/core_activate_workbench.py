# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.activate_workbench``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Internal VibeCAD session tool: switch the live FreeCAD GUI '
                'workbench without refreshing the workspace tool pack. Models '
                'switch workspaces with core.enter_workspace instead.',
 'name': 'core.activate_workbench',
 'parameters': {'properties': {'name': {'description': 'Workbench name such as '
                                                       'PartWorkbench or '
                                                       'SketcherWorkbench.',
                                        'type': 'string'}},
                'required': ['name'],
                'type': 'object'},
 'safety': 'VIEW'}


def run(service, **kwargs):
    name = kwargs["name"]
    try:
        import FreeCADGui as Gui

        before = _active_workbench_name(Gui)
        Gui.activateWorkbench(name)
        after = _active_workbench_name(Gui)
        return {"ok": after == name, "requested": name, "before": before, "active_workbench": after}
    except Exception as exc:
        return {"ok": False, "requested": name, "active_workbench": None, "error": str(exc)}


def _active_workbench_name(gui):
    try:
        workbench = gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None
