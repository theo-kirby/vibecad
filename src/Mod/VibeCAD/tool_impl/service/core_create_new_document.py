# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.create_new_document``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'description': 'Create a new FreeCAD document and make it active.',
 'name': 'core.create_new_document',
 'parameters': {'properties': {'name': {'description': 'Document name; defaults to '
                                                       'VibeCAD.',
                                        'type': 'string'}},
                'type': 'object'},
 'safety': 'SAFE_WRITE'}


def run(service, name: str = "VibeCAD") -> dict[str, Any]:
    def _create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.newDocument(str(name or "VibeCAD"))
        try:
            import FreeCADGui as Gui

            Gui.ActiveDocument = Gui.getDocument(doc.Name)
            Gui.updateGui()
        except Exception:
            pass
        return {
            "document": doc.Name,
            "label": getattr(doc, "Label", doc.Name),
            "document_summary": _active_document_summary(service),
        }

    transaction = run_freecad_transaction("Create new FreeCAD document", _create)
    return {"ok": bool(transaction.get("ok")), "transaction": transaction}


def _active_document_summary(service):
    doc = service._active_document()
    if doc is None:
        return {"document": None, "objects": []}
    objects = [service._document_object_summary(obj) for obj in doc.Objects]
    visible_objects, bounds = service._bounded_items(objects, 25)
    return {
        "document": doc.Name,
        "label": getattr(doc, "Label", doc.Name),
        "object_count": len(doc.Objects),
        "object_limit": bounds["limit"],
        "objects_truncated": bounds["truncated"],
        "objects_omitted": bounds["omitted"],
        "objects": visible_objects,
    }
