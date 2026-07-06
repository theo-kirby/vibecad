# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.wait_for_user_gui_action``."""

from __future__ import annotations

import time


TOOL_SPEC = {'description': 'Pause up to timeout_seconds while the user completes a GUI '
                'click/dialog/task-panel action, then return updated document, '
                'selection, task-panel, and workbench state.',
 'name': 'core.wait_for_user_gui_action',
 'parameters': {'properties': {'timeout_seconds': {'description': 'Maximum seconds to '
                                                                  'wait (clamped to '
                                                                  '30).',
                                                   'type': 'number'}},
                'type': 'object'},
 'safety': 'VIEW'}


def run(service, **kwargs):
    seconds = 0.0 if kwargs.get("timeout_seconds") is None else max(0.0, min(float(kwargs["timeout_seconds"]), 30.0))
    if seconds:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                import FreeCADGui as Gui

                Gui.updateGui()
            except Exception:
                pass
            time.sleep(0.05)
    from . import core_get_active_document, core_get_selection, core_get_task_panel

    return {
        "ok": True,
        "active_workbench": _active_workbench_name(),
        "task_panel": core_get_task_panel.run(service),
        "selection": core_get_selection.run(service),
        "document": core_get_active_document.run(service),
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
