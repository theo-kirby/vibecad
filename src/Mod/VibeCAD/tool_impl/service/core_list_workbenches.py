# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_workbenches``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Return registered FreeCAD workbenches and the active workbench.',
 'name': 'core.list_workbenches',
 'safety': 'READ'}


def run(service, **kwargs):
    try:
        import FreeCADGui as Gui

        return {
            "active_workbench": _active_workbench_name(Gui),
            "workbenches": sorted(Gui.listWorkbenches().keys()),
        }
    except Exception as exc:
        return {"active_workbench": None, "workbenches": [], "error": str(exc)}


def _active_workbench_name(gui):
    try:
        workbench = gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None
