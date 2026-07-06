# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher remove-external-geometry tool."""

from __future__ import annotations

from typing import Any

from .common import active_response, external_geometry_summary, get_sketch, run_freecad_transaction


TOOL_SPEC = {
    "name": "sketcher.remove_external_geometry",
    "description": (
        "Remove one native Sketcher external geometry reference by external geometry index. "
        "List current references with sketcher.inspect_sketch include=['external_geometry']."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label. Defaults to the active edit sketch or first sketch.",
            },
            "external_geometry_index": {
                "type": "integer",
                "description": "External geometry index to remove (0-based, as reported by inspect_sketch).",
            },
        },
        "required": ["external_geometry_index"],
    },
}


def run(
    service: Any,
    sketch_name: str | None = None,
    external_geometry_index: int = 0,
) -> dict[str, Any]:
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return {"ok": False, "error": "Sketch not found.", "requested": sketch_name}
    external = external_geometry_summary(sketch)
    index = int(external_geometry_index)
    if index < 0 or index >= len(external):
        return {
            "ok": False,
            "error": f"External geometry index out of range: {index}",
            "external_geometry_count": len(external),
        }

    def _remove() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before = external_geometry_summary(target)
        target.delExternal(index)
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        after = external_geometry_summary(target)
        return {
            "sketch": target.Name,
            "deleted_external_geometry_index": index,
            "deleted_external_geometry_id": -index - 1,
            "external_geometry_count_before": len(before),
            "external_geometry_count": len(after),
            "external_geometry": after,
            "old_to_new_external_geometry_index": {
                str(old): (old if old < index else old - 1)
                for old in range(len(before))
                if old != index
            },
        }

    return active_response(service, sketch, run_freecad_transaction("Remove Sketcher external geometry", _remove))
