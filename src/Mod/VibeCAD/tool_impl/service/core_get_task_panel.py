# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_task_panel``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Return bounded visible task-panel/widget state; check after a GUI '
                'command opens a dialog or task panel.',
 'name': 'core.get_task_panel',
 'safety': 'READ'}


def run(service, **kwargs):
    try:
        import FreeCADGui as Gui

        main_window = Gui.getMainWindow()
        widgets = []
        for widget in main_window.findChildren(object):
            try:
                name = widget.objectName()
                class_name = widget.metaObject().className()
            except Exception:
                continue
            if "Task" in name or "Task" in class_name:
                widgets.append({"name": name, "class": class_name, "visible": bool(widget.isVisible())})
        return {"widgets": widgets, "count": len(widgets)}
    except Exception as exc:
        return {"widgets": [], "count": 0, "error": str(exc)}
