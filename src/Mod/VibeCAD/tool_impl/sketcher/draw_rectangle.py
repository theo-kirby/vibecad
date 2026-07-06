# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher rectangle tool."""

from __future__ import annotations

from typing import Any

from .common import active_response, get_sketch, no_sketch, run_freecad_transaction


TOOL_SPEC = {
    "name": "sketcher.draw_rectangle",
    "description": (
        "Draw a fully constrained rectangle in the active Sketcher sketch. Convenience shortcut "
        "for the common four-line case — use sketcher.add_geometry kind='polyline' for other "
        "closed profiles."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "width": {"type": "number", "description": "Rectangle width in mm along sketch X."},
            "height": {"type": "number", "description": "Rectangle height in mm along sketch Y."},
            "center_x": {"type": "number", "description": "Center X in mm. Default 0."},
            "center_y": {"type": "number", "description": "Center Y in mm. Default 0."},
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label. Defaults to the active edit sketch or first sketch.",
            },
        },
        "required": ["width", "height"],
    },
}


def run(
    service: Any,
    width: float = 10.0,
    height: float | None = None,
    center_x: float = 0.0,
    center_y: float = 0.0,
    sketch_name: str | None = None,
) -> dict[str, Any]:
    width = float(width)
    height = float(height if height is not None else width)
    if width <= 0 or height <= 0:
        return {"ok": False, "error": "Rectangle dimensions must be positive."}
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return no_sketch(sketch_name)

    def _draw() -> dict[str, Any]:
        import FreeCAD as App
        import Part
        import Sketcher

        doc = App.ActiveDocument
        target = doc.getObject(sketch.Name) if doc else sketch
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        x0 = float(center_x) - width / 2.0
        x1 = float(center_x) + width / 2.0
        y0 = float(center_y) - height / 2.0
        y1 = float(center_y) + height / 2.0
        index = int(getattr(target, "GeometryCount", len(getattr(target, "Geometry", []))))
        target.addGeometry(
            [
                Part.LineSegment(App.Vector(x0, y1, 0), App.Vector(x1, y1, 0)),
                Part.LineSegment(App.Vector(x1, y1, 0), App.Vector(x1, y0, 0)),
                Part.LineSegment(App.Vector(x1, y0, 0), App.Vector(x0, y0, 0)),
                Part.LineSegment(App.Vector(x0, y0, 0), App.Vector(x0, y1, 0)),
            ],
            False,
        )
        target.addConstraint(
            [
                Sketcher.Constraint("Coincident", index + 0, 2, index + 1, 1),
                Sketcher.Constraint("Coincident", index + 1, 2, index + 2, 1),
                Sketcher.Constraint("Coincident", index + 2, 2, index + 3, 1),
                Sketcher.Constraint("Coincident", index + 3, 2, index + 0, 1),
                Sketcher.Constraint("Horizontal", index + 0),
                Sketcher.Constraint("Horizontal", index + 2),
                Sketcher.Constraint("Vertical", index + 1),
                Sketcher.Constraint("Vertical", index + 3),
                Sketcher.Constraint("DistanceX", index + 2, 2, x0),
                Sketcher.Constraint("DistanceY", index + 2, 2, y0),
            ]
        )
        if abs(width - height) < 1e-9:
            target.addConstraint(Sketcher.Constraint("Equal", index + 2, index + 3))
            target.addConstraint(Sketcher.Constraint("Distance", index + 0, width))
        else:
            target.addConstraint(Sketcher.Constraint("Distance", index + 0, width))
            target.addConstraint(Sketcher.Constraint("Distance", index + 1, height))
        if doc is not None:
            doc.recompute()
        return {
            "sketch": target.Name,
            "geometry_index": index,
            "geometry_added": 4,
            "width": width,
            "height": height,
            "center": [float(center_x), float(center_y)],
            "geometry_count": len(getattr(target, "Geometry", [])),
            "constraint_count": len(getattr(target, "Constraints", [])),
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction(f"Draw Sketcher rectangle {width:g} x {height:g}", _draw),
    )
