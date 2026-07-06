# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_workbench_tool_packs``."""

from __future__ import annotations

from VibeCADWorkbenchTools import list_tool_packs


TOOL_SPEC = {'description': 'Return VibeCAD tool-pack metadata for all integrated workbenches.',
 'name': 'core.list_workbench_tool_packs',
 'safety': 'READ'}


def run(service, **kwargs):
    return {
        "active_workbench": _active_workbench_name(),
        "disabled_workbenches": sorted(service.disabled_workbenches()),
        "tool_packs": list_tool_packs(),
    }


def _active_workbench_name():
    try:
        import FreeCADGui as Gui

        workbench = Gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None
