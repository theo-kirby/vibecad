# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_workbench_tool_packs``."""

from __future__ import annotations

from VibeCADWorkbenchTools import list_tool_packs


TOOL_SPEC = {'description': 'Return VibeCAD tool-pack metadata for all integrated workbenches.',
 'name': 'core.list_workbench_tool_packs',
 'safety': 'READ'}


def run(service, **kwargs):
    enabled = service.enabled_native_tool_workbenches()
    native_enabled = service.native_freecad_tools_enabled()
    packs = []
    for item in list_tool_packs():
        summary = dict(item)
        summary["enabled"] = native_enabled and summary["workbench"] in enabled
        packs.append(summary)
    return {
        "active_workbench": _active_workbench_name(),
        "native_freecad_tools_enabled": native_enabled,
        "enabled_native_tool_workbenches": sorted(enabled),
        "tool_packs": packs,
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
