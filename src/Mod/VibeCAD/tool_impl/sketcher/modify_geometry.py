# SPDX-License-Identifier: LGPL-2.1-or-later

"""Consolidated native Sketcher local-geometry modification tool.

Replaces the retired single-operation tools ``sketcher.trim_geometry``,
``sketcher.extend_geometry``, ``sketcher.split_geometry``, and
``sketcher.fillet_corner`` with one operation-discriminated tool.
"""

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


OPERATIONS = ("trim", "extend", "split", "fillet")

TOOL_SPEC = {
    "name": "sketcher.modify_geometry",
    "description": (
        "Trim, extend, split, fillet, or chamfer existing Sketcher geometry. "
        "Use to repair authored curves/segments; do not use fillets as a "
        "substitute for drawing required base curves."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(OPERATIONS),
                "description": "Which modification to perform.",
            },
            "sketch_name": {
                "type": "string",
                "description": "Required sketch object name or label. The tool never chooses a target sketch implicitly.",
            },
            "geometry_index": {
                "type": "integer",
                "description": "Target geometry index for trim, extend, or split.",
            },
            "geometry_handle": {
                "type": "string",
                "description": "Semantic geometry handle for trim, extend, or split.",
            },
            "x": {"type": "number", "description": "trim/split: picked point X in sketch mm."},
            "y": {"type": "number", "description": "trim/split: picked point Y in sketch mm."},
            "endpoint": {
                "type": "string",
                "enum": ["start", "end"],
                "description": "extend: required endpoint to extend.",
            },
            "increment": {
                "type": "number",
                "description": "extend: signed extension length in mm.",
            },
            "first_geometry": {"type": "integer", "description": "fillet: first curve index."},
            "first_geometry_handle": {"type": "string", "description": "fillet: first curve handle."},
            "first_point": {
                "type": "string",
                "enum": ["start", "end"],
                "description": "fillet coincident-point mode: required endpoint of the first curve.",
            },
            "second_geometry": {"type": "integer", "description": "fillet two-curve mode: second curve index."},
            "second_geometry_handle": {"type": "string", "description": "fillet two-curve mode: second curve handle."},
            "first_reference_x": {"type": "number", "description": "fillet two-curve mode: reference point X in mm on first curve."},
            "first_reference_y": {"type": "number", "description": "fillet two-curve mode: reference point Y in mm on first curve."},
            "second_reference_x": {"type": "number", "description": "fillet two-curve mode: reference point X in mm on second curve."},
            "second_reference_y": {"type": "number", "description": "fillet two-curve mode: reference point Y in mm on second curve."},
            "radius": {"type": "number", "description": "fillet: fillet radius (or chamfer size) in mm. Must be positive."},
            "trim": {
                "type": "boolean",
                "description": "fillet: required explicit choice to trim the original corner curves.",
            },
            "preserve_corner": {
                "type": "boolean",
                "description": "fillet: required explicit choice to keep the corner point constrained.",
            },
            "chamfer": {
                "type": "boolean",
                "description": "fillet: required explicit choice; true creates a straight chamfer, false creates a rounded fillet.",
            },
        },
        "required": ["operation", "sketch_name"],
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
    operation: str = "",
    sketch_name: str | None = None,
    geometry_index: int | None = None,
    geometry_handle: str | None = None,
    x: float | None = None,
    y: float | None = None,
    endpoint: str | None = None,
    increment: float | None = None,
    first_geometry: int | None = None,
    first_geometry_handle: str | None = None,
    first_point: str | None = None,
    second_geometry: int | None = None,
    second_geometry_handle: str | None = None,
    first_reference_x: float | None = None,
    first_reference_y: float | None = None,
    second_reference_x: float | None = None,
    second_reference_y: float | None = None,
    radius: float | None = None,
    trim: bool | None = None,
    preserve_corner: bool | None = None,
    chamfer: bool | None = None,
) -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    if op not in OPERATIONS:
        return _invalid_call(
            f"Unknown operation: {operation!r}. Valid operations: {', '.join(OPERATIONS)}."
        )
    if not str(sketch_name or "").strip():
        return _invalid_call(
            "sketcher.modify_geometry requires explicit sketch_name."
        )
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return _invalid_call("Sketch not found.", requested=sketch_name)
    if op == "fillet":
        if geometry_index is not None or geometry_handle:
            return _invalid_call(
                "operation='fillet' uses first_geometry/first_geometry_handle; "
                "geometry_index/geometry_handle are only for trim, extend, or split."
            )
        if first_geometry is None and not first_geometry_handle:
            return _invalid_call(
                "operation='fillet' requires first_geometry or first_geometry_handle."
            )
        if trim is None or preserve_corner is None or chamfer is None:
            return _invalid_call(
                "operation='fillet' requires explicit trim, preserve_corner, and chamfer booleans."
            )
        return _run_fillet(
            service,
            sketch,
            first_geometry,
            first_geometry_handle,
            first_point,
            second_geometry,
            second_geometry_handle,
            first_reference_x,
            first_reference_y,
            second_reference_x,
            second_reference_y,
            radius,
            bool(trim),
            bool(preserve_corner),
            bool(chamfer),
        )
    if first_geometry is not None or first_geometry_handle:
        return _invalid_call(
            f"operation='{op}' uses geometry_index/geometry_handle; "
            "first_geometry/first_geometry_handle are only for fillet."
        )
    try:
        index = resolve_geometry_index(service, sketch, geometry_index, geometry_handle)
    except (KeyError, ValueError, RuntimeError, TypeError) as exc:
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
    if op in {"trim", "split"}:
        if x is None or y is None:
            return _invalid_call(
                f"operation='{op}' requires x and y picked-point coordinates."
            )
        return _run_trim_or_split(service, sketch, op, index, geometry_handle, float(x), float(y))
    # op == "extend"
    if endpoint is None:
        return _invalid_call("operation='extend' requires endpoint='start' or endpoint='end'.")
    clean_endpoint = str(endpoint or "").strip().lower()
    if clean_endpoint not in {"start", "end"}:
        return _invalid_call("endpoint must be start or end.")
    if increment is None:
        return _invalid_call("operation='extend' requires increment.")
    return _run_extend(service, sketch, index, geometry_handle, clean_endpoint, float(increment))


def _run_trim_or_split(
    service: Any,
    sketch: Any,
    op: str,
    index: int,
    geometry_handle: str | None,
    x: float,
    y: float,
) -> dict[str, Any]:
    def _mutate() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_geometry = len(getattr(target, "Geometry", []))
        before_constraints = len(getattr(target, "Constraints", []))
        if op == "trim":
            target.trim(index, App.Vector(x, y, 0.0))
        else:
            target.split(index, App.Vector(x, y, 0.0))
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        after_geometry = len(getattr(target, "Geometry", []))
        after_constraints = len(getattr(target, "Constraints", []))
        return {
            "sketch": target.Name,
            "operation": op,
            "geometry_index": index,
            "geometry_handle": geometry_handle or f"geometry:{index}",
            "picked_point": [x, y],
            "geometry_count_before": before_geometry,
            "geometry_count": after_geometry,
            "constraint_count_before": before_constraints,
            "constraint_count": after_constraints,
            "geometry_added": max(0, after_geometry - before_geometry),
            "constraints_added": max(0, after_constraints - before_constraints),
        }

    label = "Trim Sketcher geometry" if op == "trim" else "Split Sketcher geometry"
    return active_response(service, sketch, run_freecad_transaction(label, _mutate))


def _run_extend(
    service: Any,
    sketch: Any,
    index: int,
    geometry_handle: str | None,
    endpoint: str,
    increment: float,
) -> dict[str, Any]:
    def _extend() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_geometry = len(getattr(target, "Geometry", []))
        before_constraints = len(getattr(target, "Constraints", []))
        target.extend(index, increment, point_position(endpoint))
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        after_geometry = len(getattr(target, "Geometry", []))
        after_constraints = len(getattr(target, "Constraints", []))
        return {
            "sketch": target.Name,
            "operation": "extend",
            "geometry_index": index,
            "geometry_handle": geometry_handle or f"geometry:{index}",
            "endpoint": endpoint,
            "increment": increment,
            "geometry_count_before": before_geometry,
            "geometry_count": after_geometry,
            "constraint_count_before": before_constraints,
            "constraint_count": after_constraints,
        }

    return active_response(service, sketch, run_freecad_transaction("Extend Sketcher geometry", _extend))


def _run_fillet(
    service: Any,
    sketch: Any,
    first_geometry: int | None,
    first_geometry_handle: str | None,
    first_point: str,
    second_geometry: int | None,
    second_geometry_handle: str | None,
    first_reference_x: float | None,
    first_reference_y: float | None,
    second_reference_x: float | None,
    second_reference_y: float | None,
    radius: float | None,
    trim: bool,
    preserve_corner: bool,
    chamfer: bool,
) -> dict[str, Any]:
    if radius is None or float(radius) <= 0:
        return _invalid_call("operation='fillet' requires a positive radius.")
    if second_geometry is None and not second_geometry_handle:
        if first_point is None:
            return _invalid_call(
                "operation='fillet' without second_geometry requires first_point='start' or first_point='end'."
            )
        if str(first_point or "").strip().lower() not in {"start", "end"}:
            return _invalid_call("first_point must be start or end.")
    try:
        first_index = resolve_geometry_index(service, sketch, first_geometry, first_geometry_handle)
        second_index = (
            resolve_geometry_index(service, sketch, second_geometry, second_geometry_handle)
            if second_geometry is not None or second_geometry_handle
            else None
        )
    except (KeyError, ValueError, RuntimeError, TypeError) as exc:
        return _invalid_call(str(exc))
    invalid = validate_geometry_index(sketch, first_index)
    if invalid:
        invalid.setdefault("retry_same_call", False)
        invalid.setdefault("recoverable", True)
        return invalid
    if second_index is not None:
        invalid = validate_geometry_index(sketch, second_index)
        if invalid:
            invalid.setdefault("retry_same_call", False)
            invalid.setdefault("recoverable", True)
            return invalid
    resolved_references = _resolve_fillet_references(
        sketch,
        first_index,
        second_index,
        first_reference_x,
        first_reference_y,
        second_reference_x,
        second_reference_y,
        float(radius),
    )
    if not resolved_references.get("ok"):
        resolved_references.setdefault("retry_same_call", False)
        resolved_references.setdefault("recoverable", True)
        return resolved_references

    def _fillet() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_geometry = len(getattr(target, "Geometry", []))
        before_constraints = len(getattr(target, "Constraints", []))
        if second_index is None:
            target.fillet(
                first_index,
                point_position(str(first_point).strip().lower()),
                float(radius),
                int(bool(trim)),
                bool(preserve_corner),
                bool(chamfer),
            )
            reference_mode = "coincident_point"
        else:
            first_ref = resolved_references["first_reference"]
            second_ref = resolved_references["second_reference"]
            target.fillet(
                first_index,
                second_index,
                App.Vector(float(first_ref[0]), float(first_ref[1]), 0.0),
                App.Vector(float(second_ref[0]), float(second_ref[1]), 0.0),
                float(radius),
                int(bool(trim)),
                bool(preserve_corner),
                bool(chamfer),
            )
            reference_mode = str(resolved_references["reference_mode"])
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        after_geometry = len(getattr(target, "Geometry", []))
        after_constraints = len(getattr(target, "Constraints", []))
        return {
            "sketch": target.Name,
            "operation": "fillet",
            "geometry_index": before_geometry,
            "geometry_added": max(0, after_geometry - before_geometry),
            "constraint_index": before_constraints,
            "constraints_added": max(0, after_constraints - before_constraints),
            "first_geometry": first_index,
            "first_geometry_handle": first_geometry_handle or f"geometry:{first_index}",
            "second_geometry": second_index,
            "second_geometry_handle": second_geometry_handle
            or (f"geometry:{second_index}" if second_index is not None else None),
            "reference_mode": reference_mode,
            "first_reference": resolved_references.get("first_reference"),
            "second_reference": resolved_references.get("second_reference"),
            "radius": float(radius),
            "trim": bool(trim),
            "preserve_corner": bool(preserve_corner),
            "chamfer": bool(chamfer),
            "geometry_count_before": before_geometry,
            "geometry_count": after_geometry,
            "constraint_count_before": before_constraints,
            "constraint_count": after_constraints,
        }

    return active_response(service, sketch, run_freecad_transaction("Create Sketcher fillet/chamfer", _fillet))


def _point_xy(point: Any) -> tuple[float, float] | None:
    try:
        return (float(point.x), float(point.y))
    except Exception:
        return None


def _geometry_endpoints(geometry: Any) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    for role, attr in (("start", "StartPoint"), ("end", "EndPoint")):
        point = _point_xy(getattr(geometry, attr, None))
        if point is not None:
            endpoints.append({"role": role, "point": [point[0], point[1]]})
    return endpoints


def _endpoint_candidates(sketch: Any, first_index: int, second_index: int | None) -> dict[str, Any]:
    geometry = list(getattr(sketch, "Geometry", []) or [])
    result: dict[str, Any] = {
        "first_geometry": first_index,
        "first_endpoints": _geometry_endpoints(geometry[first_index]) if 0 <= first_index < len(geometry) else [],
    }
    if second_index is not None:
        result["second_geometry"] = second_index
        result["second_endpoints"] = (
            _geometry_endpoints(geometry[second_index]) if 0 <= second_index < len(geometry) else []
        )
    return result


def _resolve_fillet_references(
    sketch: Any,
    first_index: int,
    second_index: int | None,
    first_reference_x: float | None,
    first_reference_y: float | None,
    second_reference_x: float | None,
    second_reference_y: float | None,
    radius: float,
) -> dict[str, Any]:
    if second_index is None:
        return {"ok": True, "reference_mode": "coincident_point"}
    if None not in (first_reference_x, first_reference_y, second_reference_x, second_reference_y):
        return {
            "ok": True,
            "reference_mode": "explicit_two_curve_references",
            "first_reference": [float(first_reference_x), float(first_reference_y)],
            "second_reference": [float(second_reference_x), float(second_reference_y)],
        }
    return {
        "ok": False,
        "error": (
            "operation='fillet' with second_geometry requires explicit "
            "first_reference_x/y and second_reference_x/y pick points; the tool "
            "does not infer which side of the two curves to fillet."
        ),
        "reference_mode": "missing_explicit_two_curve_references",
        "endpoint_candidates": _endpoint_candidates(sketch, first_index, second_index),
        "required_next_action": {
            "tool": "sketcher.modify_geometry",
            "arguments": {
                "operation": "fillet",
                "sketch_name": getattr(sketch, "Name", None),
                "first_geometry": first_index,
                "second_geometry": second_index,
                "first_reference_x": "<point on first curve near desired corner>",
                "first_reference_y": "<point on first curve near desired corner>",
                "second_reference_x": "<point on second curve near desired corner>",
                "second_reference_y": "<point on second curve near desired corner>",
                "radius": radius,
            },
            "why": "The tool cannot infer which side of the two curves to fillet.",
        },
    }
