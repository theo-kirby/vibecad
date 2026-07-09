# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher slot profile tool."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

from .common import active_response, get_sketch, no_sketch, run_freecad_transaction


TOOL_SPEC = {
    "name": "sketcher.add_slot",
    "description": (
        "Add one constrained slot profile: two straight sides and two "
        "semicircular ends. Provide exactly one of overall_length or "
        "center_distance."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label.",
            },
            "center_x": {"type": "number", "description": "Slot center X in mm."},
            "center_y": {"type": "number", "description": "Slot center Y in mm."},
            "overall_length": {
                "type": "number",
                "description": "Overall end-to-end slot length in mm including both semicircular ends.",
            },
            "center_distance": {
                "type": "number",
                "description": "Distance in mm between the two semicircular arc centers.",
            },
            "width": {"type": "number", "description": "Slot width (arc diameter) in mm."},
            "angle_degrees": {"type": "number", "description": "Explicit slot axis rotation in degrees."},
            "construction": {"type": "boolean", "description": "Whether to create as construction geometry."},
        },
        "required": [
            "sketch_name",
            "center_x",
            "center_y",
            "width",
            "angle_degrees",
            "construction",
        ],
        "anyOf": [
            {"required": ["overall_length"]},
            {"required": ["center_distance"]},
        ],
    },
}


def _number_arg(name: str, value: Any) -> tuple[bool, float | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit number."
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{name} must be a number."
    return True, float(value)


def run(
    service: Any,
    sketch_name: str | None = None,
    center_x: float | None = None,
    center_y: float | None = None,
    overall_length: float | None = None,
    center_distance: float | None = None,
    width: float | None = None,
    angle_degrees: float | None = None,
    construction: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if kwargs:
        unsupported = ", ".join(sorted(str(key) for key in kwargs))
        return {
            "ok": False,
            "error": (
                f"Unsupported slot parameter(s): {unsupported}. Use exactly "
                "one of overall_length or center_distance."
            ),
            "retry_same_call": False,
        }
    if not str(sketch_name or "").strip():
        return {
            "ok": False,
            "error": "sketch_name is required for sketcher.add_slot.",
            "retry_same_call": False,
        }
    parsed: dict[str, float] = {}
    for name, value in (
        ("center_x", center_x),
        ("center_y", center_y),
        ("width", width),
        ("angle_degrees", angle_degrees),
    ):
        ok, result = _number_arg(name, value)
        if not ok:
            return {"ok": False, "error": str(result), "retry_same_call": False}
        parsed[name] = float(result)
    if parsed["width"] <= 0:
        return {"ok": False, "error": "Slot width must be positive.", "retry_same_call": False}
    if construction is None or not isinstance(construction, bool):
        return {
            "ok": False,
            "error": "construction is required and must be true or false.",
            "retry_same_call": False,
        }
    length_data = _resolve_slot_lengths(parsed["width"], overall_length, center_distance)
    if not length_data["ok"]:
        return length_data
    overall = float(length_data["overall_length"])
    center_to_center = float(length_data["center_distance"])
    if overall <= 0:
        return {"ok": False, "error": "Slot length and width must be positive.", "retry_same_call": False}
    if center_to_center <= 0:
        return {
            "ok": False,
            "error": "Slot center distance must be positive; overall length must be greater than width.",
            "retry_same_call": False,
        }
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
        angle = math.radians(parsed["angle_degrees"])
        axis = App.Vector(math.cos(angle), math.sin(angle), 0.0)
        normal = App.Vector(-math.sin(angle), math.cos(angle), 0.0)
        center = App.Vector(parsed["center_x"], parsed["center_y"], 0.0)
        radius = parsed["width"] / 2.0
        straight_length = center_to_center
        left_center = center - axis * (straight_length / 2.0)
        right_center = center + axis * (straight_length / 2.0)
        left_top = left_center + normal * radius
        right_top = right_center + normal * radius
        right_bottom = right_center - normal * radius
        left_bottom = left_center - normal * radius
        left_outer = left_center - axis * radius
        right_outer = right_center + axis * radius
        target.addGeometry(
            [
                Part.LineSegment(left_top, right_top),
                Part.ArcOfCircle(right_top, right_center + axis * radius, right_bottom),
                Part.LineSegment(right_bottom, left_bottom),
                Part.ArcOfCircle(left_bottom, left_center - axis * radius, left_top),
            ],
            bool(construction),
        )
        base_index = before_geometry
        constraints = [
            Sketcher.Constraint("Block", base_index + 0),
            Sketcher.Constraint("Block", base_index + 1),
            Sketcher.Constraint("Block", base_index + 2),
            Sketcher.Constraint("Block", base_index + 3),
        ]
        target.addConstraint(constraints)
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        try:
            degrees_of_freedom = int(getattr(target, "DoF"))
        except Exception:
            degrees_of_freedom = None
        fully_constrained = degrees_of_freedom == 0 if degrees_of_freedom is not None else False
        profile_status = service._sketch_profile_status(target)
        if profile_status.get("ready_for_pocket"):
            suggested_next_actions = [
                {
                    "tool": "partdesign.extrude",
                    "arguments": {"operation": "pocket", "sketch_name": target.Name},
                    "why": "Use this fully constrained closed slot profile for a subtractive feature when it is mapped to a solid face.",
                },
            ]
        else:
            suggested_next_actions = [
                {
                    "tool": "sketcher.inspect_sketch",
                    "arguments": {"sketch_name": target.Name, "include": ["profile_deep"]},
                    "why": "Inspect why this slot profile is not yet feature-ready before creating a PartDesign feature.",
                },
                {
                    "tool": "sketcher.add_constraint",
                    "arguments": {
                        "sketch_name": target.Name,
                        "constraint_type": "Lock",
                        "first_geometry": base_index + 1,
                        "first_point": "center",
                        "x": float(right_center.x),
                        "y": float(right_center.y),
                    },
                    "why": "Lock one slot arc center to place the slot without using opaque block constraints.",
                },
                {
                    "tool": "sketcher.add_constraint",
                    "arguments": {
                        "sketch_name": target.Name,
                        "constraint_type": "Angle",
                        "first_geometry": base_index,
                        "value": parsed["angle_degrees"],
                    },
                    "why": "Constrain the slot axis angle when orientation must be explicit.",
                },
            ]
        return {
            "sketch": target.Name,
            "geometry_index": base_index,
            "geometry_added": 4,
            "created_geometry_indices": [base_index, base_index + 1, base_index + 2, base_index + 3],
            "constraint_count_before": before_constraints,
            "constraint_index": before_constraints,
            "constraints_added": len(constraints),
            "created_constraint_indices": list(range(before_constraints, before_constraints + len(constraints))),
            "geometry_count_before": before_geometry,
            "geometry_count": len(getattr(target, "Geometry", [])),
            "constraint_count": len(getattr(target, "Constraints", [])),
            "center": [parsed["center_x"], parsed["center_y"]],
            "overall_length": overall,
            "center_distance": center_to_center,
            "straight_segment_length": center_to_center,
            "width": parsed["width"],
            "radius": radius,
            "angle_degrees": parsed["angle_degrees"],
            "arc_centers": {
                "left": [float(left_center.x), float(left_center.y)],
                "right": [float(right_center.x), float(right_center.y)],
            },
            "profile_points": {
                "left_top": [float(left_top.x), float(left_top.y)],
                "right_top": [float(right_top.x), float(right_top.y)],
                "right_bottom": [float(right_bottom.x), float(right_bottom.y)],
                "left_bottom": [float(left_bottom.x), float(left_bottom.y)],
                "left_outer": [float(left_outer.x), float(left_outer.y)],
                "right_outer": [float(right_outer.x), float(right_outer.y)],
            },
            "bounding_box": _bounding_box([left_top, right_top, right_bottom, left_bottom, left_outer, right_outer]),
            "degrees_of_freedom": degrees_of_freedom,
            "fully_constrained": fully_constrained,
            "construction": bool(construction),
            "suggested_next_actions": suggested_next_actions,
        }

    return active_response(service, sketch, run_freecad_transaction("Add Sketcher slot", _add))


def _resolve_slot_lengths(
    width: float,
    overall_length: float | None,
    center_distance: float | None,
) -> dict[str, Any]:
    if overall_length is not None and center_distance is not None:
        return {
            "ok": False,
            "error": "Provide only one of overall_length or center_distance.",
            "retry_same_call": False,
        }
    if overall_length is not None:
        ok, parsed_overall = _number_arg("overall_length", overall_length)
        if not ok:
            return {"ok": False, "error": str(parsed_overall), "retry_same_call": False}
        overall = float(parsed_overall)
        center_to_center = overall - width
    elif center_distance is not None:
        ok, parsed_center_distance = _number_arg("center_distance", center_distance)
        if not ok:
            return {"ok": False, "error": str(parsed_center_distance), "retry_same_call": False}
        center_to_center = float(parsed_center_distance)
        overall = center_to_center + width
    else:
        return {
            "ok": False,
            "error": "Provide exactly one of overall_length or center_distance.",
            "retry_same_call": False,
        }
    if overall <= 0 or center_to_center <= 0:
        return {
            "ok": False,
            "error": "Slot overall length must be greater than width, and center distance must be positive.",
            "overall_length": overall,
            "center_distance": center_to_center,
            "width": width,
            "retry_same_call": False,
        }
    return {
        "ok": True,
        "overall_length": overall,
        "center_distance": center_to_center,
    }


def _bounding_box(points):
    xs = [float(point.x) for point in points]
    ys = [float(point.y) for point in points]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
    }
