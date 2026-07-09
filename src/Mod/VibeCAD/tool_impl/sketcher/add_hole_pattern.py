# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher hole-pattern helper."""

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any

from .common import (
    active_response,
    geometry_fingerprint,
    geometry_metadata,
    get_sketch,
    no_sketch,
    run_freecad_transaction,
    set_geometry_metadata,
)


TOOL_SPEC = {
    "name": "sketcher.add_hole_pattern",
    "description": (
        "Add a fully constrained Sketcher hole/bolt pattern for pockets, "
        "drilled holes, vents, and repeated circular cuts."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label.",
            },
            "pattern": {
                "type": "string",
                "enum": ["rectangular", "linear", "circular"],
                "description": "Explicit pattern layout.",
            },
            "hole_diameter": {"type": "number", "description": "Hole diameter in millimeters."},
            "center_x": {"type": "number", "description": "Pattern center X in mm."},
            "center_y": {"type": "number", "description": "Pattern center Y in mm."},
            "count_x": {"type": "integer", "description": "Rectangular/linear column count."},
            "count_y": {"type": "integer", "description": "Rectangular row count."},
            "spacing_x": {"type": "number", "description": "Rectangular/linear X spacing in mm, or total span when count_x=2."},
            "spacing_y": {"type": "number", "description": "Rectangular Y spacing in mm, or total span when count_y=2."},
            "count": {"type": "integer", "description": "Linear or circular occurrence count."},
            "linear_angle_degrees": {"type": "number", "description": "Linear pattern direction angle in degrees."},
            "bolt_circle_diameter": {"type": "number", "description": "Circular pattern pitch-circle diameter in mm."},
            "start_angle_degrees": {"type": "number", "description": "Circular pattern first-hole angle in degrees."},
            "name_prefix": {"type": "string", "description": "Semantic geometry name prefix."},
            "construction": {"type": "boolean", "description": "Whether to create holes as construction geometry."},
            "lock_centers": {"type": "boolean", "description": "Whether to constrain hole centers with dimensional constraints."},
            "equal_radii": {"type": "boolean", "description": "Whether to add Equal constraints so all holes share one radius."},
        },
        "required": [
            "sketch_name",
            "pattern",
            "hole_diameter",
            "center_x",
            "center_y",
            "name_prefix",
            "construction",
            "lock_centers",
            "equal_radii",
        ],
    },
}


def _validation_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False}


def _number_arg(name: str, value: Any) -> tuple[bool, float | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit number."
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{name} must be a number."
    return True, float(value)


def _integer_arg(name: str, value: Any) -> tuple[bool, int | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit integer."
    if isinstance(value, bool) or not isinstance(value, Integral):
        return False, f"{name} must be an integer."
    return True, int(value)


def _bool_arg(name: str, value: Any) -> tuple[bool, bool | str]:
    if value is None:
        return False, f"{name} is required and must be true or false."
    if not isinstance(value, bool):
        return False, f"{name} must be true or false."
    return True, value


def run(
    service: Any,
    sketch_name: str | None = None,
    pattern: str | None = None,
    hole_diameter: float | None = None,
    center_x: float | None = None,
    center_y: float | None = None,
    count_x: int | None = None,
    count_y: int | None = None,
    spacing_x: float | None = None,
    spacing_y: float | None = None,
    count: int | None = None,
    linear_angle_degrees: float | None = None,
    bolt_circle_diameter: float | None = None,
    start_angle_degrees: float | None = None,
    name_prefix: str | None = None,
    construction: bool | None = None,
    lock_centers: bool | None = None,
    equal_radii: bool | None = None,
) -> dict[str, Any]:
    if not str(sketch_name or "").strip():
        return _validation_error("sketch_name is required for sketcher.add_hole_pattern.")
    clean_pattern = str(pattern or "").strip().lower()
    if clean_pattern not in {"rectangular", "linear", "circular"}:
        return _validation_error("pattern must be rectangular, linear, or circular.")
    clean_prefix = str(name_prefix or "").strip()
    if not clean_prefix:
        return _validation_error("name_prefix is required for sketcher.add_hole_pattern.")
    parsed_numbers: dict[str, float] = {}
    for name, value in (
        ("hole_diameter", hole_diameter),
        ("center_x", center_x),
        ("center_y", center_y),
    ):
        ok, result = _number_arg(name, value)
        if not ok:
            return _validation_error(str(result))
        parsed_numbers[name] = float(result)
    diameter = parsed_numbers["hole_diameter"]
    if diameter <= 0:
        return _validation_error("hole_diameter must be positive.")
    ok, parsed_construction = _bool_arg("construction", construction)
    if not ok:
        return _validation_error(str(parsed_construction))
    ok, parsed_lock_centers = _bool_arg("lock_centers", lock_centers)
    if not ok:
        return _validation_error(str(parsed_lock_centers))
    ok, parsed_equal_radii = _bool_arg("equal_radii", equal_radii)
    if not ok:
        return _validation_error(str(parsed_equal_radii))
    pattern_args: dict[str, float | int | None] = {
        "count_x": None,
        "count_y": None,
        "spacing_x": None,
        "spacing_y": None,
        "count": None,
        "linear_angle_degrees": None,
        "bolt_circle_diameter": None,
        "start_angle_degrees": None,
    }
    if clean_pattern == "rectangular":
        for name, value in (("count_x", count_x), ("count_y", count_y)):
            ok, result = _integer_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            pattern_args[name] = int(result)
        for name, value in (("spacing_x", spacing_x), ("spacing_y", spacing_y)):
            ok, result = _number_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            pattern_args[name] = float(result)
    elif clean_pattern == "linear":
        ok, result = _integer_arg("count", count)
        if not ok:
            return _validation_error(str(result))
        pattern_args["count"] = int(result)
        for name, value in (
            ("spacing_x", spacing_x),
            ("linear_angle_degrees", linear_angle_degrees),
        ):
            ok, result = _number_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            pattern_args[name] = float(result)
    else:
        ok, result = _integer_arg("count", count)
        if not ok:
            return _validation_error(str(result))
        pattern_args["count"] = int(result)
        for name, value in (
            ("bolt_circle_diameter", bolt_circle_diameter),
            ("start_angle_degrees", start_angle_degrees),
        ):
            ok, result = _number_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            pattern_args[name] = float(result)
    try:
        centers = _centers(
            clean_pattern,
            center_x=parsed_numbers["center_x"],
            center_y=parsed_numbers["center_y"],
            count_x=pattern_args["count_x"],
            count_y=pattern_args["count_y"],
            spacing_x=pattern_args["spacing_x"],
            spacing_y=pattern_args["spacing_y"],
            count=pattern_args["count"],
            linear_angle_degrees=pattern_args["linear_angle_degrees"],
            bolt_circle_diameter=pattern_args["bolt_circle_diameter"],
            start_angle_degrees=pattern_args["start_angle_degrees"],
        )
    except ValueError as exc:
        return _validation_error(str(exc))
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return no_sketch(sketch_name)

    def _add() -> dict[str, Any]:
        import FreeCAD as App
        import Part
        import Sketcher

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before_geometry = len(getattr(target, "Geometry", []))
        before_constraints = len(getattr(target, "Constraints", []))
        radius = diameter / 2.0
        created: list[int] = []
        constraints: list[Any] = []
        for x, y in centers:
            geometry_index = target.addGeometry(
                Part.Circle(
                    App.Vector(float(x), float(y), 0.0),
                    App.Vector(0.0, 0.0, 1.0),
                    radius,
                ),
                bool(parsed_construction),
            )
            created.append(int(geometry_index))
        if created:
            constraints.append(Sketcher.Constraint("Radius", created[0], radius))
        if parsed_equal_radii:
            constraints.extend(
                Sketcher.Constraint("Equal", created[0], index)
                for index in created[1:]
            )
        else:
            constraints.extend(
                Sketcher.Constraint("Radius", index, radius)
                for index in created[1:]
            )
        if parsed_lock_centers:
            for index, (x, y) in zip(created, centers):
                constraints.append(Sketcher.Constraint("DistanceX", index, 3, float(x)))
                constraints.append(Sketcher.Constraint("DistanceY", index, 3, float(y)))
        if constraints:
            target.addConstraint(constraints)
            constraint_index = before_constraints
        else:
            constraint_index = []
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        _name_geometry(service, target, created, clean_prefix)
        if doc is not None:
            doc.recompute()
        return {
            "sketch": target.Name,
            "pattern": clean_pattern,
            "geometry_index": created[0] if created else None,
            "created_geometry_indices": created,
            "geometry_added": len(created),
            "constraint_index": _constraint_indices(constraint_index),
            "constraints_added": len(constraints),
            "created_constraint_indices": list(range(before_constraints, before_constraints + len(constraints))),
            "geometry_count_before": before_geometry,
            "geometry_count": len(getattr(target, "Geometry", [])),
            "constraint_count_before": before_constraints,
            "constraint_count": len(getattr(target, "Constraints", [])),
            "hole_diameter": diameter,
            "hole_radius": radius,
            "centers": [[float(x), float(y)] for x, y in centers],
            "semantic_handles": [
                f"name:{clean_prefix}_{offset}"
                for offset in range(1, len(created) + 1)
            ],
            "construction": bool(parsed_construction),
            "lock_centers": bool(parsed_lock_centers),
            "equal_radii": bool(parsed_equal_radii),
            "suggested_next_actions": [
                {
                    "tool": "partdesign.extrude",
                    "arguments": {"operation": "pocket", "sketch_name": target.Name},
                    "why": "Cut these closed hole profiles through the active solid.",
                },
                {
                    "tool": "partdesign.hole_from_sketch",
                    "arguments": {
                        "sketch_name": target.Name,
                        "diameter": diameter,
                        "depth_type": 1,
                        "hole_cut_type": 0,
                    },
                    "why": (
                        "Create native plain through-all PartDesign holes from "
                        "this constrained hole sketch when that matches intent; "
                        "choose blind depth or counterbore/countersink parameters explicitly otherwise."
                    ),
                },
            ],
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction(f"Add Sketcher {clean_pattern} hole pattern", _add),
    )


def _centers(
    pattern: str,
    *,
    center_x: float,
    center_y: float,
    count_x: int | None,
    count_y: int | None,
    spacing_x: float | None,
    spacing_y: float | None,
    count: int | None,
    linear_angle_degrees: float | None,
    bolt_circle_diameter: float | None,
    start_angle_degrees: float | None,
) -> list[tuple[float, float]]:
    if pattern == "rectangular":
        if count_x is None or count_y is None or spacing_x is None or spacing_y is None:
            raise ValueError("count_x, count_y, spacing_x, and spacing_y are required for rectangular hole patterns.")
        if count_x <= 0 or count_y <= 0:
            raise ValueError("count_x and count_y must be positive for rectangular hole patterns.")
        if count_x == 1 and count_y == 1:
            return [(center_x, center_y)]
        if count_x > 1 and spacing_x <= 0:
            raise ValueError("spacing_x must be positive when count_x is greater than 1.")
        if count_y > 1 and spacing_y <= 0:
            raise ValueError("spacing_y must be positive when count_y is greater than 1.")
        x0 = center_x - spacing_x * (count_x - 1) / 2.0
        y0 = center_y - spacing_y * (count_y - 1) / 2.0
        return [
            (x0 + column * spacing_x, y0 + row * spacing_y)
            for row in range(count_y)
            for column in range(count_x)
        ]
    if pattern == "linear":
        if count is None or spacing_x is None or linear_angle_degrees is None:
            raise ValueError("count, spacing_x, and linear_angle_degrees are required for linear hole patterns.")
        if count <= 0:
            raise ValueError("count must be positive for linear hole patterns.")
        if count == 1:
            return [(center_x, center_y)]
        if spacing_x <= 0:
            raise ValueError("spacing_x must be positive for linear hole patterns.")
        angle = math.radians(linear_angle_degrees)
        dx = math.cos(angle) * spacing_x
        dy = math.sin(angle) * spacing_x
        start = -(count - 1) / 2.0
        return [
            (center_x + (start + offset) * dx, center_y + (start + offset) * dy)
            for offset in range(count)
        ]
    if pattern == "circular":
        if count is None or bolt_circle_diameter is None or start_angle_degrees is None:
            raise ValueError("count, bolt_circle_diameter, and start_angle_degrees are required for circular hole patterns.")
        if count < 2:
            raise ValueError("count must be at least 2 for circular hole patterns.")
        if bolt_circle_diameter is None or float(bolt_circle_diameter) <= 0:
            raise ValueError("bolt_circle_diameter must be positive for circular hole patterns.")
        radius = float(bolt_circle_diameter) / 2.0
        start = math.radians(start_angle_degrees)
        return [
            (
                center_x + math.cos(start + 2.0 * math.pi * offset / count) * radius,
                center_y + math.sin(start + 2.0 * math.pi * offset / count) * radius,
            )
            for offset in range(count)
        ]
    raise ValueError("pattern must be rectangular, linear, or circular.")


def _constraint_indices(raw_value: Any) -> int | list[int]:
    if isinstance(raw_value, int):
        return int(raw_value)
    if isinstance(raw_value, (list, tuple)):
        flattened: list[int] = []
        for item in raw_value:
            if isinstance(item, (list, tuple)):
                flattened.extend(int(value) for value in item)
            else:
                flattened.append(int(item))
        return flattened
    if raw_value is None:
        return []
    try:
        return int(raw_value)
    except Exception:
        return []


def _name_geometry(service: Any, sketch: Any, indices: list[int], prefix: str) -> None:
    metadata = geometry_metadata(sketch)
    names = metadata.setdefault("names", {})
    geometry = service.sketcher_summary(getattr(sketch, "Name", None)).get("geometry", [])
    for offset, index in enumerate(indices, start=1):
        if 0 <= index < len(geometry):
            names[f"{prefix}_{offset}"] = {
                "index": index,
                "fingerprint": geometry_fingerprint(geometry[index]),
            }
    set_geometry_metadata(sketch, metadata)
