# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``draft.create_wire``.

Creates true 3D curves (interpolated B-splines or polylines) through
arbitrary points in space. Sketches are planar by construction; this tool
covers the non-planar cases: sweep spines, surface boundary curves, and
space curves that no single sketch plane can express.
"""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_CURVE_TYPES = ("bspline", "polyline")

TOOL_SPEC = {
    "description": (
        "Create a true 3D curve through arbitrary points in space: "
        "curve_type='bspline' interpolates a smooth B-spline, "
        "curve_type='polyline' connects the points with straight segments. "
        "Use this when geometry cannot live on a single sketch plane — "
        "non-planar sweep spines, boundary curves for "
        "surface.create_surface, and space curves with twist. Points are "
        "absolute document coordinates in mm; closed=true joins the last "
        "point back to the first."
    ),
    "name": "draft.create_wire",
    "parameters": {
        "properties": {
            "points": {
                "description": (
                    "Ordered 3D points, each {x, y, z} in mm (at least 2)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                },
                "type": "array",
            },
            "curve_type": {
                "description": "bspline: smooth interpolation; polyline: straight segments.",
                "enum": list(_CURVE_TYPES),
                "type": "string",
            },
            "closed": {
                "description": "Close the curve back to the first point (default false).",
                "type": "boolean",
            },
            "label": {"type": "string"},
        },
        "required": ["points"],
        "type": "object",
    },
    "safety": "SAFE_WRITE",
    "workbench": "DraftWorkbench",
    "contextual": True,
}


def _parse_points(raw_points: list[Any]) -> tuple[list[tuple[float, float, float]], str | None]:
    points: list[tuple[float, float, float]] = []
    for entry in raw_points:
        if not isinstance(entry, dict):
            return [], f"Each point must be an object with x/y/z, got: {entry!r}"
        try:
            points.append(
                (
                    float(entry.get("x", 0.0)),
                    float(entry.get("y", 0.0)),
                    float(entry.get("z", 0.0)),
                )
            )
        except (TypeError, ValueError):
            return [], f"Point coordinates must be numbers, got: {entry!r}"
    return points, None


def run(
    service,
    points: list[dict[str, Any]],
    curve_type: str = "bspline",
    closed: bool = False,
    label: str = "VibeCAD Wire",
) -> dict[str, Any]:
    kind = str(curve_type or "bspline").strip().lower()
    if kind not in _CURVE_TYPES:
        return {
            "ok": False,
            "error": f"curve_type must be one of {list(_CURVE_TYPES)}.",
        }
    parsed, error = _parse_points(points or [])
    if error:
        return {"ok": False, "error": error}
    if len(parsed) < 2:
        return {"ok": False, "error": "At least two points are required."}
    deduped = [
        point for index, point in enumerate(parsed) if index == 0 or point != parsed[index - 1]
    ]
    if len(deduped) < 2:
        return {"ok": False, "error": "Points are all coincident; a curve needs distinct points."}
    if kind == "bspline" and bool(closed) and len(deduped) < 3:
        return {"ok": False, "error": "A closed bspline needs at least three distinct points."}

    def _create() -> dict[str, Any]:
        import Draft
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        vectors = [App.Vector(x, y, z) for x, y, z in deduped]
        if kind == "bspline":
            wire_obj = Draft.make_bspline(vectors, closed=bool(closed), face=False)
        else:
            wire_obj = Draft.make_wire(vectors, closed=bool(closed), face=False)
        if wire_obj is None:
            raise RuntimeError("Draft could not create the curve from these points.")
        wire_obj.Label = label or "VibeCAD Wire"
        doc.recompute()
        shape = getattr(wire_obj, "Shape", None)
        edges = list(getattr(shape, "Edges", []) or [])
        if shape is None or shape.isNull() or not edges:
            raise RuntimeError("Curve object recomputed without a usable shape.")
        return {
            "object": wire_obj.Name,
            "label": wire_obj.Label,
            "type": getattr(wire_obj, "TypeId", ""),
            "curve_type": kind,
            "closed": bool(closed),
            "point_count": len(deduped),
            "edge_count": len(edges),
            "length_mm": round(float(getattr(shape, "Length", 0.0) or 0.0), 3),
        }

    transaction = run_freecad_transaction(
        f"Create Draft 3D {kind}: {label}",
        _create,
    )
    return {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "draft": domain_runtime.draft_summary(service),
    }
