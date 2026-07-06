# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_view_state``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Return active view and workbench state.',
 'name': 'core.get_view_state',
 'safety': 'VIEW'}


def run(service, **kwargs):
    state = {
        "active_workbench": _active_workbench_name(),
        "active_document": _active_document_name(),
        "last_view_screenshot": dict(service._last_view_screenshot) if service._last_view_screenshot else {"captured": False, "path": None},
    }
    try:
        import FreeCADGui as Gui

        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is not None:
            state["view"] = {
                "type": type(view).__name__,
                "camera": str(view.getCamera())[:500],
            }
    except Exception as exc:
        state["view_error"] = str(exc)
    return state


def _active_workbench_name():
    try:
        import FreeCADGui as Gui

        workbench = Gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None


def _active_document_name():
    try:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is not None:
            return doc.Name
    except Exception:
        pass
    return None
