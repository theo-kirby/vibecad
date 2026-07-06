# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_active_workbench_tool_pack``."""

from __future__ import annotations

from VibeCADWorkbenchTools import get_tool_pack


TOOL_SPEC = {'contextual': True,
 'description': 'Return the VibeCAD tool-pack metadata for the active workbench.',
 'name': 'core.get_active_workbench_tool_pack',
 'safety': 'READ'}


def run(service, **kwargs):
    active = kwargs.get("workbench") or _active_workbench_name()
    pack = get_tool_pack(active)
    if pack is None:
        return {
            "active_workbench": active,
            "tool_pack": None,
            "enabled": service.is_workbench_tool_pack_enabled(active),
        }
    return {
        "active_workbench": active,
        "tool_pack": pack.workbench,
        "domain": pack.domain,
        "enabled": service.is_workbench_tool_pack_enabled(active),
        "command_prefixes": list(pack.command_prefixes),
        "object_templates": list(pack.object_templates),
        "object_types": list(pack.object_types),
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
