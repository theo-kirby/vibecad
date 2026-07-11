# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher point/geometry move tool."""

from __future__ import annotations

from typing import Any

from .common import (
    active_response,
    geometry_handle as stable_geometry_handle,
    geometry_fingerprint,
    get_sketch,
    resolve_geometry_index,
    run_freecad_transaction,
    solver_status,
    validate_geometry_index,
)
from .constrain_common import point_position


TOOL_SPEC = {
    "name": "sketcher.move_point",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Move one Sketcher point role or whole geometry to an absolute or "
        "relative 2D location. A whole-geometry move is relative only. The "
        "result proves the achieved position instead of assuming the solver moved it."
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
                "description": (
                    "Preferred stable tag:<uuid> handle from live sketch state. "
                    "Unlike an index, it survives deletion of other geometry."
                ),
            },
            "point": {
                "type": "string",
                "enum": ["whole", "start", "end", "center"],
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
        "allOf": [
            {
                "if": {"properties": {"point": {"const": "whole"}}},
                "then": {"properties": {"relative": {"const": True}}},
            }
        ],
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
    if clean_point not in {"whole", "start", "end", "center"}:
        return _invalid_call(
            "point must be one of: center, end, start, whole."
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

    try:
        before_point = _point_for_move(service, sketch, index, clean_point)
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        return _invalid_call(
            str(exc),
            geometry_index=index,
            geometry_handle=stable_geometry_handle(sketch, index),
            point=clean_point,
            allowed_point_roles=_available_move_roles(
                list(getattr(sketch, "Geometry", []) or [])[index]
            ),
        )
    before_solver = solver_status(service, sketch)
    requested_point = (
        [before_point[0] + float(x), before_point[1] + float(y)]
        if relative
        else [float(x), float(y)]
    )

    def _move() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_geometry = service._geometry_summary(
            list(getattr(target, "Geometry", []))[index], index, target
        )
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
        after_point = _point_for_move(service, target, index, clean_point)
        error_x = float(after_point[0]) - float(requested_point[0])
        error_y = float(after_point[1]) - float(requested_point[1])
        displacement_error = (error_x * error_x + error_y * error_y) ** 0.5
        before_fingerprint = geometry_fingerprint(before_geometry)
        after_fingerprint = geometry_fingerprint(geometry)
        effect_applied = before_fingerprint != after_fingerprint
        after_solver = solver_status(service, target)
        return {
            "sketch": target.Name,
            "geometry_index": index,
            "geometry_handle": stable_geometry_handle(target, index),
            "point": clean_point,
            "point_position": pos,
            "x": float(x),
            "y": float(y),
            "relative": bool(relative),
            "requested_point": requested_point,
            "before_point": before_point,
            "after_point": after_point,
            "displacement_error_mm": displacement_error,
            "effect_applied": effect_applied,
            "degrees_of_freedom_before": before_solver.get("degrees_of_freedom"),
            "degrees_of_freedom_after": after_solver.get("degrees_of_freedom"),
            "geometry": geometry,
        }

    def _verify(result: dict[str, Any]) -> dict[str, Any]:
        effect = bool(result.get("effect_applied"))
        error = float(result.get("displacement_error_mm") or 0.0)
        return {
            "ok": effect and error <= 1.0e-7,
            "checks": [
                {
                    "name": "requested_point_achieved",
                    "ok": effect and error <= 1.0e-7,
                    "effect_applied": effect,
                    "displacement_error_mm": error,
                    "tolerance_mm": 1.0e-7,
                }
            ],
            "error": (
                None
                if effect and error <= 1.0e-7
                else "Sketcher solver did not apply the requested point position."
            ),
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction(
            "Move Sketcher geometry point", _move, verifier=_verify
        ),
    )


def _available_move_roles(geometry: Any) -> list[str]:
    roles = ["whole"]
    if getattr(geometry, "StartPoint", None) is not None:
        roles.append("start")
    if getattr(geometry, "EndPoint", None) is not None:
        roles.append("end")
    if getattr(geometry, "Center", None) is not None:
        roles.append("center")
    return roles


def _xy(value: Any) -> list[float]:
    return [float(value.x), float(value.y)]


def _point_for_move(
    service: Any, sketch: Any, index: int, role: str
) -> list[float]:
    geometry = list(getattr(sketch, "Geometry", []) or [])[index]
    if role == "start":
        return _xy(geometry.StartPoint)
    if role == "end":
        return _xy(geometry.EndPoint)
    if role == "center":
        center = getattr(geometry, "Center", None)
        if center is None:
            raise ValueError(
                f"{type(geometry).__name__} has no movable center."
            )
        return _xy(center)
    summary = service._geometry_summary(geometry, index, sketch)
    bounds = summary.get("actual_bounds")
    if not isinstance(bounds, dict) or not isinstance(bounds.get("center"), list):
        raise ValueError(
            f"{type(geometry).__name__} has no measurable whole-geometry anchor."
        )
    return [float(bounds["center"][0]), float(bounds["center"][1])]
