# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_selection``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Return the current FreeCAD selection summary.',
 'name': 'core.get_selection',
 'safety': 'READ'}


def run(service, **kwargs):
    try:
        import FreeCADGui as Gui

        selection = Gui.Selection.getSelectionEx()
    except Exception as exc:
        return {"selection": [], "error": str(exc)}

    items = []
    for item in selection:
        obj = getattr(item, "Object", None)
        if obj is None:
            continue
        items.append(
            {
                "object": service._document_object_summary(obj),
                "sub_objects": list(getattr(item, "SubElementNames", []) or []),
            }
        )
    return {"selection": items, "count": len(items)}
