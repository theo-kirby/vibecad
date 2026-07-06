# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_active_document``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Return the active FreeCAD document summary.',
 'name': 'core.get_active_document',
 'safety': 'READ'}


def run(service, **kwargs):
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
