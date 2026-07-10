# SPDX-License-Identifier: LGPL-2.1-or-later

"""Delete one exact native document object without rollback or cascade guesses."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import (
    _document_delta,
    _document_snapshot,
    report_view_error_summary,
)


TOOL_SPEC = {
    "name": "core.delete_object",
    "description": (
        "Delete exactly one object from the active document by internal name. For a Body member, "
        "FreeCAD's native Body removal reroutes Tip/BaseFeature before document deletion."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {"object_name": {"type": "string"}},
        "required": ["object_name"],
        "additionalProperties": False,
    },
}


def run(service: Any, object_name: str) -> dict[str, Any]:
    doc = service._active_document()
    clean_name = str(object_name or "").strip()
    target = doc.getObject(clean_name) if doc is not None and clean_name else None
    if doc is None:
        return _invalid("No active document.")
    if target is None:
        return _invalid(f"Object not found by exact internal name: {clean_name}")
    owner = service._partdesign_body_for_feature(target)
    before = _document_snapshot(doc)
    target_summary = service._document_object_summary(target)
    body_before = service._partdesign_body_summary(owner) if owner is not None else None
    incoming_before = [_object_ref(item) for item in list(getattr(target, "InList", []) or [])]
    outgoing_before = [_object_ref(item) for item in list(getattr(target, "OutList", []) or [])]
    report_view_error_summary()
    opened = False
    removal_error = None
    recompute_error = None
    commit_error = None
    body_membership_removed = False
    try:
        if hasattr(doc, "openTransaction"):
            doc.openTransaction(f"Delete object: {clean_name}")
            opened = True
        if owner is not None and target in list(owner.Group):
            removed = list(owner.removeObject(target))
            body_membership_removed = target in removed
        doc.removeObject(clean_name)
        try:
            doc.recompute()
        except Exception as exc:
            recompute_error = str(exc)
        if opened and hasattr(doc, "commitTransaction"):
            try:
                doc.commitTransaction()
            except Exception as exc:
                commit_error = str(exc)
            opened = False
    except Exception as exc:
        removal_error = str(exc)
        if opened and hasattr(doc, "commitTransaction"):
            try:
                doc.commitTransaction()
            except Exception as commit_exc:
                commit_error = str(commit_exc)
            opened = False
    after = _document_snapshot(doc)
    still_present = doc.getObject(clean_name) is not None
    report_errors = report_view_error_summary()
    body_after_object = service._get_partdesign_body(owner.Name) if owner is not None else None
    ok = not still_present and removal_error is None and commit_error is None
    response = {
        "ok": ok,
        "operation": "delete_object",
        "deleted_object": target_summary,
        "exact_internal_name": clean_name,
        "partdesign_owner": getattr(owner, "Name", None),
        "body_membership_removed": body_membership_removed,
        "incoming_references_before": incoming_before,
        "outgoing_references_before": outgoing_before,
        "body_state_before": body_before,
        "body_state_after": (
            service._partdesign_body_summary(body_after_object)
            if body_after_object is not None
            else None
        ),
        "document_delta": _document_delta(before, after),
        "still_present": still_present,
        "recompute_error": recompute_error,
        "native_errors": list(report_errors.get("errors", []) or []),
        "committed_transaction": opened is False and commit_error is None,
    }
    if not ok:
        response["error"] = (
            removal_error
            or commit_error
            or f"FreeCAD still contains object {clean_name} after deletion."
        )
        response["retry_same_call"] = False
    return response


def _object_ref(obj: Any) -> dict[str, Any]:
    return {
        "name": getattr(obj, "Name", None),
        "label": getattr(obj, "Label", getattr(obj, "Name", None)),
        "type": getattr(obj, "TypeId", None),
    }


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
