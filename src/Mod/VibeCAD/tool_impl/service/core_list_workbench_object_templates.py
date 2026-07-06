# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_workbench_object_templates``."""

from __future__ import annotations

from VibeCADWorkbenchTools import get_tool_pack


TOOL_SPEC = {'contextual': True,
 'description': 'Return object templates available in a VibeCAD workbench tool pack.',
 'name': 'core.list_workbench_object_templates',
 'parameters': {'properties': {'workbench': {'description': 'Optional workbench name. '
                                                            'Defaults to the active '
                                                            'workbench.',
                                             'type': 'string'}},
                'type': 'object'},
 'safety': 'READ'}


def run(service, **kwargs):
    active = kwargs.get("workbench") or _active_workbench_name()
    pack = get_tool_pack(active)
    return {
        "active_workbench": active,
        "tool_pack": pack.workbench if pack else None,
        "object_templates": list(pack.object_templates) if pack else [],
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
