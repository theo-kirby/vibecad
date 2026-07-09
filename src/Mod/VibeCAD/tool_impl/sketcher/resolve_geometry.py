# SPDX-License-Identifier: LGPL-2.1-or-later

"""Resolve VibeCAD Sketcher geometry handles to current native indices."""

from __future__ import annotations

from typing import Any

from .common import get_sketch, resolve_geometry_index, resolve_geometry_names


TOOL_SPEC = {
    "name": "sketcher.resolve_geometry",
    "description": (
        "Resolve a Sketcher geometry handle such as geometry:3 or name:mount_slot_axis "
        "to the current native geometry index and geometry summary."
    ),
    "contextual": True,
    "safety": "READ",
    "parameters": {
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label. Defaults to the active edit sketch or first sketch.",
            },
            "geometry_handle": {
                "type": "string",
                "description": "Handle to resolve: geometry:N, name:X, origin, axis:H, axis:V, or external:N.",
            },
        },
        "required": ["geometry_handle"],
    },
}


def run(service: Any, geometry_handle: str, sketch_name: str | None = None) -> dict[str, Any]:
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return {"ok": False, "error": "Sketch not found.", "requested": sketch_name}
    try:
        index = resolve_geometry_index(service, sketch, geometry_handle=geometry_handle)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "geometry_handle": str(geometry_handle),
            "named_geometry": resolve_geometry_names(service, sketch, include_missing=True),
        }
    geometry = service.sketcher_summary(getattr(sketch, "Name", None)).get("geometry", [])
    return {
        "ok": True,
        "sketch": getattr(sketch, "Name", None),
        "geometry_handle": str(geometry_handle),
        "geometry_index": index,
        "geometry": geometry[index] if 0 <= index < len(geometry) else None,
    }
