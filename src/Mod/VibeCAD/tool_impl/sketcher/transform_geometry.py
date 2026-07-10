# SPDX-License-Identifier: LGPL-2.1-or-later

"""Consolidated native Sketcher bulk geometry transform tool.

Replaces the retired single-operation tools ``sketcher.transform_geometry``
(translate), ``sketcher.copy_geometry``, ``sketcher.mirror_geometry``,
``sketcher.offset_geometry``, and ``sketcher.rectangular_array`` with one
operation-discriminated tool.
"""

from __future__ import annotations

import math
from typing import Any

from .common import (
    active_response,
    get_sketch,
    resolve_geometry_index,
    run_freecad_transaction,
    validate_geometry_index,
)


OPERATIONS = ("translate", "copy", "mirror", "offset", "array")

_GEOMETRY_REFERENCE = {
    "oneOf": [
        {"type": "integer", "minimum": 0},
        {"type": "string", "minLength": 1},
    ]
}

_VECTOR = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
}


def _action_schema(
    operation: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "const": operation},
            **properties,
        },
        "required": ["operation", *required],
        "additionalProperties": False,
    }


TOOL_SPEC = {
    "name": "sketcher.transform_geometry",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Move, copy, mirror, offset, or array existing Sketcher geometry. "
        "Choose one explicit action shape; only arguments valid for that native "
        "transform are accepted."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "geometry": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _GEOMETRY_REFERENCE,
                "description": "Exact geometry indices or stable handles from live sketch state.",
            },
            "action": {
                "oneOf": [
                    _action_schema("translate", {"delta_mm": _VECTOR}, ["delta_mm"]),
                    _action_schema("copy", {"delta_mm": _VECTOR}, ["delta_mm"]),
                    _action_schema(
                        "mirror",
                        {
                            "axis_point_mm": _VECTOR,
                            "axis_direction": _VECTOR,
                            "keep_original": {"type": "boolean"},
                        },
                        ["axis_point_mm", "axis_direction", "keep_original"],
                    ),
                    _action_schema(
                        "offset",
                        {
                            "distance_mm": {"type": "number"},
                            "side": {
                                "type": "string",
                                "enum": ["left", "right", "outward", "inward"],
                            },
                            "created_geometry": {
                                "type": "string",
                                "enum": ["match_source", "regular", "construction"],
                            },
                        },
                        ["distance_mm", "side", "created_geometry"],
                    ),
                    _action_schema(
                        "array",
                        {
                            "columns": {"type": "integer", "minimum": 1},
                            "rows": {"type": "integer", "minimum": 1},
                            "column_step_mm": _VECTOR,
                            "row_step_mm": _VECTOR,
                            "include_origin_copy": {"type": "boolean"},
                        },
                        [
                            "columns",
                            "rows",
                            "column_step_mm",
                            "row_step_mm",
                            "include_origin_copy",
                        ],
                    ),
                ],
            },
        },
        "required": ["geometry", "action"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    geometry: list[int | str],
    action: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(geometry, list) or not geometry:
        return {
            "ok": False,
            "error": "geometry must contain at least one exact reference.",
        }
    if not isinstance(action, dict):
        return {"ok": False, "error": "action must be one structured transform object."}
    op = str(action.get("operation") or "").strip().lower()
    if op not in OPERATIONS:
        return {
            "ok": False,
            "error": f"Unknown operation: {op!r}. Valid operations: {', '.join(OPERATIONS)}.",
        }
    sketch = get_sketch(service)
    if sketch is None:
        return {
            "ok": False,
            "error": "No Sketcher sketch is currently open for editing.",
        }
    try:
        indices, handles = _resolve_references(service, sketch, geometry)
    except (KeyError, ValueError, RuntimeError, TypeError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "geometry": geometry,
        }
    if not indices:
        return {
            "ok": False,
            "error": "At least one geometry index or handle is required.",
        }
    for index in indices:
        invalid = validate_geometry_index(sketch, index)
        if invalid:
            return invalid

    if op in {"translate", "copy"}:
        delta = action.get("delta_mm")
        if not _is_vector2(delta):
            return {"ok": False, "error": f"operation='{op}' requires delta_mm=[x, y]."}
        if op == "translate":
            return _run_translate(
                service, sketch, indices, handles, float(delta[0]), float(delta[1])
            )
        return _run_copy(
            service, sketch, indices, handles, float(delta[0]), float(delta[1])
        )
    if op == "mirror":
        axis_point = action.get("axis_point_mm")
        axis_direction = action.get("axis_direction")
        if not _is_vector2(axis_point) or not _is_vector2(axis_direction):
            return {
                "ok": False,
                "error": "operation='mirror' requires axis_point_mm=[x, y] and axis_direction=[x, y].",
            }
        if (
            abs(float(axis_direction[0])) < 1e-12
            and abs(float(axis_direction[1])) < 1e-12
        ):
            return {
                "ok": False,
                "error": "Mirror axis direction vector must be non-zero.",
            }
        if not isinstance(action.get("keep_original"), bool):
            return {
                "ok": False,
                "error": "operation='mirror' requires keep_original=true or false.",
            }
        return _run_mirror(
            service,
            sketch,
            indices,
            handles,
            float(axis_point[0]),
            float(axis_point[1]),
            float(axis_direction[0]),
            float(axis_direction[1]),
            action["keep_original"],
        )
    if op == "offset":
        distance = action.get("distance_mm")
        if distance is None:
            return {"ok": False, "error": "operation='offset' requires distance_mm."}
        if abs(float(distance)) < 1e-12:
            return {"ok": False, "error": "Offset distance must be non-zero."}
        geometry_mode = str(action.get("created_geometry") or "")
        if geometry_mode not in {"match_source", "regular", "construction"}:
            return {
                "ok": False,
                "error": "operation='offset' created_geometry must be match_source, regular, or construction.",
            }
        side = str(action.get("side") or "")
        if side not in {"left", "right", "outward", "inward"}:
            return {
                "ok": False,
                "error": "operation='offset' side must be left, right, outward, or inward.",
            }
        construction = (
            None if geometry_mode == "match_source" else geometry_mode == "construction"
        )
        return _run_offset(
            service,
            sketch,
            indices,
            handles,
            float(distance),
            side,
            construction,
        )
    # op == "array"
    columns = action.get("columns")
    rows = action.get("rows")
    column_step = action.get("column_step_mm")
    row_step = action.get("row_step_mm")
    if (
        columns is None
        or rows is None
        or not _is_vector2(column_step)
        or not _is_vector2(row_step)
    ):
        return {
            "ok": False,
            "error": "operation='array' requires columns, rows, column_step_mm=[x, y], and row_step_mm=[x, y].",
        }
    if int(columns) < 1 or int(rows) < 1:
        return {"ok": False, "error": "columns and rows must be at least 1."}
    if not isinstance(action.get("include_origin_copy"), bool):
        return {
            "ok": False,
            "error": "operation='array' requires include_origin_copy=true or false.",
        }
    include_original = action["include_origin_copy"]
    if int(columns) == 1 and int(rows) == 1 and not include_original:
        return {
            "ok": False,
            "error": "Array would create no new geometry; increase rows/columns or set include_original.",
        }
    return _run_array(
        service,
        sketch,
        indices,
        handles,
        int(columns),
        int(rows),
        float(column_step[0]),
        float(column_step[1]),
        float(row_step[0]),
        float(row_step[1]),
        bool(include_original),
    )


def _is_vector2(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    if any(isinstance(item, bool) for item in value):
        return False
    try:
        float(value[0])
        float(value[1])
    except (TypeError, ValueError):
        return False
    return True


def _run_translate(
    service: Any,
    sketch: Any,
    indices: list[int],
    geometry_handles: list[str] | None,
    dx: float,
    dy: float,
) -> dict[str, Any]:
    def _transform() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        for index in indices:
            target.moveGeometry(index, 0, App.Vector(dx, dy, 0.0), 1)
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        geometry = [
            service._geometry_summary(
                list(getattr(target, "Geometry", []))[index], index, target
            )
            for index in indices
        ]
        return {
            "sketch": target.Name,
            "operation": "translate",
            "modified_geometry_indices": indices,
            "geometry_indices": indices,
            "geometry_handles": geometry_handles
            or [f"geometry:{index}" for index in indices],
            "dx": dx,
            "dy": dy,
            "geometry": geometry,
            "old_to_new_geometry_index": {
                str(index): index
                for index in range(len(getattr(target, "Geometry", [])))
            },
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction("Transform Sketcher geometry", _transform),
    )


def _run_copy(
    service: Any,
    sketch: Any,
    indices: list[int],
    geometry_handles: list[str] | None,
    dx: float,
    dy: float,
) -> dict[str, Any]:
    def _copy() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_count = len(getattr(target, "Geometry", []))
        created: list[int] = []
        vector = App.Vector(dx, dy, 0.0)
        source_geometry = list(getattr(target, "Geometry", []))
        for index in indices:
            source = source_geometry[index]
            copied = source.copy()
            copied.translate(vector)
            copy_construction = bool(target.getConstruction(index))
            created.append(int(target.addGeometry(copied, copy_construction)))
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        geometry = [
            service._geometry_summary(
                list(getattr(target, "Geometry", []))[index], index, target
            )
            for index in created
        ]
        return {
            "sketch": target.Name,
            "operation": "copy",
            "source_geometry_indices": indices,
            "source_geometry_handles": geometry_handles
            or [f"geometry:{index}" for index in indices],
            "created_geometry_indices": created,
            "geometry_index": created[0] if created else None,
            "geometry_added": len(created),
            "geometry_count_before": before_count,
            "geometry_count": len(getattr(target, "Geometry", [])),
            "dx": dx,
            "dy": dy,
            "geometry": geometry,
            "old_to_new_geometry_index": {
                str(index): index
                for index in range(len(getattr(target, "Geometry", [])))
            },
        }

    return active_response(
        service, sketch, run_freecad_transaction("Copy Sketcher geometry", _copy)
    )


def _run_mirror(
    service: Any,
    sketch: Any,
    indices: list[int],
    geometry_handles: list[str] | None,
    axis_point_x: float,
    axis_point_y: float,
    axis_direction_x: float,
    axis_direction_y: float,
    keep_original: bool,
) -> dict[str, Any]:
    def _mirror() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_count = len(getattr(target, "Geometry", []))
        created: list[int] = []
        modified: list[int] = []
        source_geometry = list(getattr(target, "Geometry", []))
        axis_point = App.Vector(axis_point_x, axis_point_y, 0.0)
        axis_direction = App.Vector(axis_direction_x, axis_direction_y, 0.0)
        for index in indices:
            mirrored = source_geometry[index].copy()
            mirrored.mirror(axis_point, axis_direction)
            if keep_original:
                mirror_construction = bool(target.getConstruction(index))
                created.append(int(target.addGeometry(mirrored, mirror_construction)))
            else:
                target.setGeometry(index, mirrored)
                modified.append(index)
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        all_geometry = list(getattr(target, "Geometry", []))
        affected = created if keep_original else modified
        geometry = [
            service._geometry_summary(all_geometry[index], index, target)
            for index in affected
        ]
        return {
            "sketch": target.Name,
            "operation": "mirror",
            "source_geometry_indices": indices,
            "source_geometry_handles": geometry_handles
            or [f"geometry:{index}" for index in indices],
            "created_geometry_indices": created,
            "modified_geometry_indices": modified,
            "geometry_index": created[0] if created else None,
            "geometry_added": len(created),
            "geometry_count_before": before_count,
            "geometry_count": len(all_geometry),
            "mirror_axis": {
                "point": [axis_point_x, axis_point_y],
                "direction": [axis_direction_x, axis_direction_y],
            },
            "keep_original": keep_original,
            "geometry": geometry,
            "old_to_new_geometry_index": {
                str(index): index for index in range(len(all_geometry))
            },
        }

    return active_response(
        service, sketch, run_freecad_transaction("Mirror Sketcher geometry", _mirror)
    )


def _run_offset(
    service: Any,
    sketch: Any,
    indices: list[int],
    geometry_handles: list[str] | None,
    distance: float,
    side: str,
    construction: bool | None,
) -> dict[str, Any]:
    def _offset() -> dict[str, Any]:
        import FreeCAD as App
        import Part

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_count = len(getattr(target, "Geometry", []))
        created: list[int] = []
        source_geometry = list(getattr(target, "Geometry", []))
        normalized_side = str(side or "left").strip().lower()
        for index in indices:
            source = source_geometry[index]
            offset = _offset_one(App, Part, source, distance, normalized_side)
            if offset is None:
                raise RuntimeError(
                    "Offset currently supports LineSegment, Circle, and ArcOfCircle geometry; "
                    f"geometry {index} is {type(source).__name__}."
                )
            offset_construction = (
                bool(target.getConstruction(index))
                if construction is None
                else bool(construction)
            )
            created.append(int(target.addGeometry(offset, offset_construction)))
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        all_geometry = list(getattr(target, "Geometry", []))
        geometry = [
            service._geometry_summary(all_geometry[index], index, target)
            for index in created
        ]
        return {
            "sketch": target.Name,
            "operation": "offset",
            "source_geometry_indices": indices,
            "source_geometry_handles": geometry_handles
            or [f"geometry:{index}" for index in indices],
            "created_geometry_indices": created,
            "geometry_index": created[0] if created else None,
            "geometry_added": len(created),
            "geometry_count_before": before_count,
            "geometry_count": len(all_geometry),
            "distance": distance,
            "side": normalized_side,
            "construction": construction,
            "geometry": geometry,
            "old_to_new_geometry_index": {
                str(index): index for index in range(len(all_geometry))
            },
        }

    return active_response(
        service, sketch, run_freecad_transaction("Offset Sketcher geometry", _offset)
    )


def _run_array(
    service: Any,
    sketch: Any,
    indices: list[int],
    geometry_handles: list[str] | None,
    columns: int,
    rows: int,
    column_dx: float,
    column_dy: float,
    row_dx: float,
    row_dy: float,
    include_original: bool,
) -> dict[str, Any]:
    def _array() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_count = len(getattr(target, "Geometry", []))
        created: list[int] = []
        source_geometry = list(getattr(target, "Geometry", []))
        source_handles = geometry_handles or [f"geometry:{index}" for index in indices]
        placements: list[dict[str, Any]] = []
        for row in range(rows):
            for column in range(columns):
                if row == 0 and column == 0 and not include_original:
                    continue
                dx = column_dx * column + row_dx * row
                dy = column_dy * column + row_dy * row
                vector = App.Vector(dx, dy, 0.0)
                for index in indices:
                    source = source_geometry[index]
                    copied = source.copy()
                    copied.translate(vector)
                    array_construction = bool(target.getConstruction(index))
                    new_index = int(target.addGeometry(copied, array_construction))
                    created.append(new_index)
                    placements.append(
                        {
                            "row": row,
                            "column": column,
                            "source_geometry_index": index,
                            "created_geometry_index": new_index,
                            "dx": dx,
                            "dy": dy,
                        }
                    )
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        geometry = [
            service._geometry_summary(
                list(getattr(target, "Geometry", []))[index], index, target
            )
            for index in created
        ]
        return {
            "sketch": target.Name,
            "operation": "array",
            "source_geometry_indices": indices,
            "source_geometry_handles": source_handles,
            "created_geometry_indices": created,
            "geometry_index": created[0] if created else None,
            "geometry_added": len(created),
            "geometry_count_before": before_count,
            "geometry_count": len(getattr(target, "Geometry", [])),
            "columns": columns,
            "rows": rows,
            "column_vector": [column_dx, column_dy],
            "row_vector": [row_dx, row_dy],
            "include_original": include_original,
            "placements": placements,
            "geometry": geometry,
            "old_to_new_geometry_index": {
                str(index): index
                for index in range(len(getattr(target, "Geometry", [])))
            },
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction("Create Sketcher rectangular array", _array),
    )


def _offset_one(App: Any, Part: Any, source: Any, distance: float, side: str) -> Any:
    name = type(source).__name__
    if name == "LineSegment":
        start = source.StartPoint
        end = source.EndPoint
        dx = float(end.x) - float(start.x)
        dy = float(end.y) - float(start.y)
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            raise RuntimeError("Cannot offset a zero-length line segment.")
        sign = -1.0 if side == "right" else 1.0
        vector = App.Vector(
            -dy / length * distance * sign, dx / length * distance * sign, 0.0
        )
        return Part.LineSegment(start + vector, end + vector)
    if name == "Circle":
        radius = _offset_radius(float(source.Radius), distance, side)
        return Part.Circle(source.Center, source.Axis, radius)
    if name == "ArcOfCircle":
        radius = _offset_radius(float(source.Radius), distance, side)
        circle = Part.Circle(source.Center, source.Axis, radius)
        return Part.ArcOfCircle(
            circle, float(source.FirstParameter), float(source.LastParameter)
        )
    return None


def _offset_radius(radius: float, distance: float, side: str) -> float:
    if side == "inward":
        result = radius - abs(distance)
    elif side == "outward":
        result = radius + abs(distance)
    else:
        result = radius + distance
    if result <= 1e-12:
        raise RuntimeError("Offset radius must remain positive.")
    return result


def _resolve_references(
    service: Any,
    sketch: Any,
    references: list[int | str] | None,
) -> tuple[list[int], list[str]]:
    resolved: list[int] = []
    handles: list[str] = []
    for reference in references or []:
        if isinstance(reference, bool):
            raise ValueError("Geometry references must be indices or stable handles.")
        if isinstance(reference, int):
            index = int(reference)
            handle = f"geometry:{index}"
        elif isinstance(reference, str) and reference.strip():
            handle = reference.strip()
            index = resolve_geometry_index(service, sketch, None, handle)
        else:
            raise ValueError("Geometry references must be indices or stable handles.")
        if index not in resolved:
            resolved.append(index)
            handles.append(handle)
    return resolved, handles
