# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher point/geometry move tool."""

from __future__ import annotations

from typing import Any

from .common import (
    active_response,
    get_sketch,
    resolve_geometry_index,
    run_freecad_transaction,
    validate_geometry_index,
)
from .constrain_common import point_position


TOOL_SPEC = {
    "name": "sketcher.move_point",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Move one Sketcher point role or whole geometry to an absolute or "
        "relative 2D location. Use transform_geometry for multi-element edits."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "geometry_index": {
                "type": "integer",
                "description": "Target geometry index.",
            },
            "geometry_handle": {
                "type": "string",
                "description": "Geometry handle (geometry:N / name:X) alternative to geometry_index.",
            },
            "point": {
                "type": "string",
                "enum": ["whole", "start", "end", "center", "midpoint"],
                "description": "Point role to move, or 'whole' to move the entire element.",
            },
            "x": {
                "type": "number",
                "description": "Target X in mm (or X delta when relative=true).",
            },
            "y": {
                "type": "number",
                "description": "Target Y in mm (or Y delta when relative=true).",
            },
            "relative": {
                "type": "boolean",
                "description": "Required explicit mode. True treats x/y as a delta; false treats x/y as an absolute sketch coordinate.",
            },
        },
        "required": ["point", "x", "y", "relative"],
        "additionalProperties": False,
    },
}


def _invalid_call(error: str, **extra: Any) -> dict[str, Any]:
    result = {
        "ok": False,
        "error": error,
        "retry_same_call": False,
        "recoverable": True,
    }
    result.update(extra)
    return result


def run(
    service: Any,
    sketch_name: str | None = None,
    geometry_index: int | None = None,
    geometry_handle: str | None = None,
    point: str | None = None,
    x: float | None = None,
    y: float | None = None,
    relative: bool | None = None,
) -> dict[str, Any]:
    if geometry_index is None and not str(geometry_handle or "").strip():
        return _invalid_call(
            "sketcher.move_point requires geometry_index or geometry_handle."
        )
    if point is None:
        return _invalid_call("sketcher.move_point requires point role.")
    clean_point = str(point or "").strip().lower()
    if clean_point not in {"whole", "start", "end", "center", "midpoint"}:
        return _invalid_call(
            "point must be one of: center, end, midpoint, start, whole."
        )
    if x is None or y is None:
        return _invalid_call("sketcher.move_point requires x and y.")
    if relative is None or not isinstance(relative, bool):
        return _invalid_call(
            "sketcher.move_point requires relative as an explicit boolean."
        )
    sketch = get_sketch(service)
    if sketch is None:
        return _invalid_call("No Sketcher sketch is currently open for editing.")
    try:
        index = resolve_geometry_index(service, sketch, geometry_index, geometry_handle)
    except Exception as exc:
        return _invalid_call(
            str(exc),
            geometry_index=geometry_index,
            geometry_handle=geometry_handle,
        )
    invalid = validate_geometry_index(sketch, index)
    if invalid:
        invalid.setdefault("retry_same_call", False)
        invalid.setdefault("recoverable", True)
        return invalid

    def _move() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        pos = point_position(clean_point)
        target.moveGeometry(
            index, pos, App.Vector(float(x), float(y), 0.0), int(bool(relative))
        )
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        geometry = service._geometry_summary(
            list(getattr(target, "Geometry", []))[index], index, target
        )
        return {
            "sketch": target.Name,
            "geometry_index": index,
            "geometry_handle": geometry_handle or f"geometry:{index}",
            "point": clean_point,
            "point_position": pos,
            "x": float(x),
            "y": float(y),
            "relative": bool(relative),
            "geometry": geometry,
        }

    return active_response(
        service, sketch, run_freecad_transaction("Move Sketcher geometry point", _move)
    )
