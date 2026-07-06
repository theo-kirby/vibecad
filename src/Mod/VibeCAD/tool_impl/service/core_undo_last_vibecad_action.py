# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.undo_last_vibecad_action``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Undo the most recent transaction on the active document undo '
                'stack; for removing a specific older object use core.delete_object.',
 'name': 'core.undo_last_vibecad_action',
 'safety': 'WRITE'}


def run(service, **kwargs):
    try:
        import FreeCAD as App
    except ImportError as exc:
        return {"ok": False, "error": f"FreeCAD unavailable: {exc}"}

    doc = App.ActiveDocument
    if doc is None or not hasattr(doc, "undo"):
        return {"ok": False, "error": "No active FreeCAD document can be undone."}

    undo_names = list(getattr(doc, "UndoNames", []) or [])
    if not undo_names and not int(getattr(doc, "UndoCount", 0) or 0):
        return {
            "ok": False,
            "error": "The document undo stack is empty; nothing to undo.",
            "document": getattr(doc, "Name", None),
        }

    undone_transaction = undo_names[0] if undo_names else None
    try:
        doc.undo()
        if hasattr(doc, "recompute"):
            doc.recompute()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "document": getattr(doc, "Name", None),
        }
    return {
        "ok": True,
        "undone_transaction": undone_transaction,
        "document": getattr(doc, "Name", None),
        "remaining_undo_count": int(getattr(doc, "UndoCount", 0) or 0),
    }
