# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.delete_object``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'description': 'Delete an object from the active document by internal name or '
                'label. Use to remove a bad modeling step; prefer '
                'core.undo_last_vibecad_action to roll back the most recent action.',
 'name': 'core.delete_object',
 'parameters': {'properties': {'object_name': {'description': 'Internal name or label of '
                                                              'the object to delete.',
                                               'type': 'string'},
                               'reason': {'description': 'Short reason for the deletion, '
                                                         'recorded in the transaction log.',
                                          'type': 'string'}},
                'required': ['object_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE'}


def run(service, object_name: str, reason: str = "") -> dict[str, Any]:
    target = service._get_document_object(object_name)
    if target is None:
        return {"ok": False, "error": f"Object not found: {object_name}", "requested": object_name}
    target_name = target.Name
    target_label = getattr(target, "Label", target.Name)
    before_summary = _active_document_summary(service)

    def _delete() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        obj = doc.getObject(target_name)
        if obj is None:
            raise RuntimeError(f"Object not found: {target_name}")
        doc.removeObject(target_name)
        doc.recompute()
        return {
            "removed": target_name,
            "removed_label": target_label,
            "reason": str(reason or ""),
            "object_count": len(doc.Objects),
        }

    transaction = run_freecad_transaction(f"Delete object {target_name}", _delete)
    after_summary = _active_document_summary(service)
    return {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "before": before_summary,
        "after": after_summary,
        "removed": target_name,
        "removed_label": target_label,
    }


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
