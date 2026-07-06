# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.open_document``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'description': 'Open an existing FreeCAD/CAD document from a local file path and make '
                'it active.',
 'name': 'core.open_document',
 'parameters': {'properties': {'file_path': {'description': 'Local path to an existing '
                                                            'document file; ~ is '
                                                            'expanded.',
                                             'type': 'string'}},
                'required': ['file_path'],
                'type': 'object'},
 'safety': 'SAFE_WRITE'}


def run(service, file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"File does not exist: {path}"}

    def _open() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.openDocument(str(path))
        try:
            import FreeCADGui as Gui

            Gui.ActiveDocument = Gui.getDocument(doc.Name)
            Gui.updateGui()
        except Exception:
            pass
        return {
            "document": doc.Name,
            "file_path": str(path),
            "document_summary": _active_document_summary(service),
        }

    transaction = run_freecad_transaction(f"Open FreeCAD document: {path}", _open)
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
