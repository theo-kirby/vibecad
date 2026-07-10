# SPDX-License-Identifier: LGPL-2.1-or-later

"""Apply a validated batch of native Sketcher constraints."""

from __future__ import annotations

from typing import Any

from . import add_constraint
from .common import active_response, get_sketch, run_freecad_transaction


_CONSTRAINT_TYPES = (
    "Horizontal",
    "Vertical",
    "Parallel",
    "Perpendicular",
    "Tangent",
    "Equal",
    "Symmetric",
    "Block",
    "Coincident",
    "PointOnObject",
    "Distance",
    "DistanceX",
    "DistanceY",
    "Radius",
    "Diameter",
    "Angle",
    "Lock",
)

_GEOMETRY = {
    "oneOf": [
        {"type": "integer", "minimum": 0},
        {"type": "string", "minLength": 1},
    ],
    "description": "Geometry index or stable handle from live sketch state.",
}

_POINT = {
    "type": "object",
    "properties": {
        "geometry": _GEOMETRY,
        "point": {
            "type": "string",
            "enum": ["start", "end", "center", "midpoint", "whole"],
        },
    },
    "required": ["geometry", "point"],
    "additionalProperties": False,
}

_POSITION = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
}


def _constraint_schema(
    constraint_type: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "const": constraint_type},
            **properties,
        },
        "required": ["type", *required],
        "additionalProperties": False,
    }


_CONSTRAINT_SCHEMAS = [
    *[
        _constraint_schema(kind, {"geometry": _GEOMETRY}, ["geometry"])
        for kind in ("Horizontal", "Vertical", "Block")
    ],
    *[
        _constraint_schema(
            kind,
            {"first": _GEOMETRY, "second": _GEOMETRY},
            ["first", "second"],
        )
        for kind in ("Parallel", "Perpendicular", "Tangent", "Equal")
    ],
    _constraint_schema(
        "Coincident",
        {"first": _POINT, "second": _POINT},
        ["first", "second"],
    ),
    _constraint_schema(
        "PointOnObject",
        {"point": _POINT, "object": _GEOMETRY},
        ["point", "object"],
    ),
    _constraint_schema(
        "Symmetric",
        {"first": _POINT, "second": _POINT, "about": _POINT},
        ["first", "second", "about"],
    ),
    *[
        _constraint_schema(
            kind,
            {
                "geometry": _GEOMETRY,
                "size_mm": {"type": "number", "exclusiveMinimum": 0},
            },
            ["geometry", "size_mm"],
        )
        for kind in ("Radius", "Diameter")
    ],
    _constraint_schema(
        "Distance",
        {
            "geometry": _GEOMETRY,
            "distance_mm": {"type": "number", "exclusiveMinimum": 0},
        },
        ["geometry", "distance_mm"],
    ),
    _constraint_schema(
        "Distance",
        {
            "first": _POINT,
            "second": _POINT,
            "distance_mm": {"type": "number", "exclusiveMinimum": 0},
        },
        ["first", "second", "distance_mm"],
    ),
    *[
        _constraint_schema(
            kind,
            {"point": _POINT, "coordinate_mm": {"type": "number"}},
            ["point", "coordinate_mm"],
        )
        for kind in ("DistanceX", "DistanceY")
    ],
    *[
        _constraint_schema(
            kind,
            {"first": _POINT, "second": _POINT, "distance_mm": {"type": "number"}},
            ["first", "second", "distance_mm"],
        )
        for kind in ("DistanceX", "DistanceY")
    ],
    _constraint_schema(
        "Angle",
        {"geometry": _GEOMETRY, "angle_degrees": {"type": "number"}},
        ["geometry", "angle_degrees"],
    ),
    _constraint_schema(
        "Angle",
        {"first": _POINT, "second": _POINT, "angle_degrees": {"type": "number"}},
        ["first", "second", "angle_degrees"],
    ),
    _constraint_schema(
        "Lock",
        {"point": _POINT, "position_mm": _POSITION},
        ["point", "position_mm"],
    ),
]


TOOL_SPEC = {
    "name": "sketcher.constrain",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Apply one validated batch of native Sketcher constraints. Each item has "
        "a constraint-specific shape with semantic point roles; the complete batch "
        "is validated against the open sketch before any constraint is added."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "constraints": {
                "type": "array",
                "minItems": 1,
                "items": {"oneOf": _CONSTRAINT_SCHEMAS},
            },
        },
        "required": ["constraints"],
        "additionalProperties": False,
    },
}


def _reference_arguments(prefix: str, reference: Any) -> dict[str, Any]:
    if isinstance(reference, dict):
        geometry = reference.get("geometry")
        point = reference.get("point")
    else:
        geometry = reference
        point = None
    if isinstance(geometry, bool):
        raise ValueError(f"{prefix}.geometry must be an index or stable handle.")
    result: dict[str, Any] = {}
    if isinstance(geometry, int):
        result[f"{prefix}_geometry"] = geometry
    elif isinstance(geometry, str) and geometry.strip():
        result[f"{prefix}_geometry_handle"] = geometry.strip()
    else:
        raise ValueError(f"{prefix}.geometry must be an index or stable handle.")
    if point is not None:
        result[f"{prefix}_point"] = str(point)
    return result


def _arguments_for_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"Constraint item {index} must be an object.")
    canonical = {name.casefold(): name for name in _CONSTRAINT_TYPES}
    constraint_type = canonical.get(str(item.get("type") or "").casefold())
    if constraint_type is None:
        raise ValueError(f"Constraint item {index} has an unsupported type.")
    arguments: dict[str, Any] = {"constraint_type": constraint_type}
    if constraint_type in {"Horizontal", "Vertical", "Block", "Radius", "Diameter"}:
        arguments.update(_reference_arguments("first", item.get("geometry")))
    elif constraint_type in {"Parallel", "Perpendicular", "Tangent", "Equal"}:
        arguments.update(_reference_arguments("first", item.get("first")))
        arguments.update(_reference_arguments("second", item.get("second")))
    elif constraint_type == "Coincident":
        arguments.update(_reference_arguments("first", item.get("first")))
        arguments.update(_reference_arguments("second", item.get("second")))
    elif constraint_type == "PointOnObject":
        arguments.update(_reference_arguments("first", item.get("point")))
        arguments.update(_reference_arguments("second", item.get("object")))
    elif constraint_type == "Symmetric":
        arguments.update(_reference_arguments("first", item.get("first")))
        arguments.update(_reference_arguments("second", item.get("second")))
        arguments.update(_reference_arguments("third", item.get("about")))
    elif constraint_type == "Distance":
        if "geometry" in item:
            arguments.update(_reference_arguments("first", item.get("geometry")))
        else:
            arguments.update(_reference_arguments("first", item.get("first")))
            arguments.update(_reference_arguments("second", item.get("second")))
        arguments["value"] = item.get("distance_mm")
    elif constraint_type in {"DistanceX", "DistanceY"}:
        if "point" in item:
            arguments.update(_reference_arguments("first", item.get("point")))
            arguments["value"] = item.get("coordinate_mm")
        else:
            arguments.update(_reference_arguments("first", item.get("first")))
            arguments.update(_reference_arguments("second", item.get("second")))
            arguments["value"] = item.get("distance_mm")
    elif constraint_type == "Angle":
        if "geometry" in item:
            arguments.update(_reference_arguments("first", item.get("geometry")))
        else:
            arguments.update(_reference_arguments("first", item.get("first")))
            arguments.update(_reference_arguments("second", item.get("second")))
        arguments["value"] = item.get("angle_degrees")
    elif constraint_type == "Lock":
        arguments.update(_reference_arguments("first", item.get("point")))
        position = item.get("position_mm")
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError(f"Constraint item {index} position_mm must be [x, y].")
        arguments["x"] = position[0]
        arguments["y"] = position[1]
    if constraint_type in {"Radius", "Diameter"}:
        arguments["value"] = item.get("size_mm")
    return arguments


def run(service: Any, constraints: list[dict[str, Any]]) -> dict[str, Any]:
    sketch = get_sketch(service)
    if sketch is None:
        return {
            "ok": False,
            "error": "No Sketcher sketch is currently open for editing.",
            "retry_same_call": False,
        }
    prepared_items: list[dict[str, Any]] = []
    native_constraints: list[Any] = []
    for index, item in enumerate(constraints):
        try:
            arguments = _arguments_for_item(item, index)
        except ValueError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_index": index,
                "validated_count": len(prepared_items),
                "mutated": False,
                "retry_same_call": False,
            }
        prepared = add_constraint.prepare_constraint(service, sketch, **arguments)
        if not prepared.get("ok"):
            return {
                "ok": False,
                "error": prepared.get("error")
                or f"Constraint item {index} is invalid.",
                "failed_index": index,
                "failed_constraint": item,
                "validated_count": len(prepared_items),
                "mutated": False,
                "details": {
                    key: value
                    for key, value in prepared.items()
                    if key != "constraints"
                },
                "retry_same_call": False,
            }
        prepared_items.append(prepared)
        native_constraints.extend(prepared["constraints"])

    def _add() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_count = len(getattr(target, "Constraints", []) or [])
        raw_indices = target.addConstraint(native_constraints)
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        return {
            "sketch": target.Name,
            "constraint_index": add_constraint._constraint_indices(raw_indices),
            "constraint_count_before": before_count,
            "constraint_count": len(getattr(target, "Constraints", []) or []),
            "constraints_added": len(native_constraints),
            "items_added": len(prepared_items),
            "resolved": [item["resolved"] for item in prepared_items],
            "constraint_types": [item["constraint_type"] for item in prepared_items],
        }

    transaction = run_freecad_transaction("Apply Sketcher constraint batch", _add)
    return active_response(service, sketch, transaction)
