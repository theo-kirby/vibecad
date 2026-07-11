# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Draft wire (polyline) from exact global points."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "draft.create_wire",
    "description": (
        "Create one native Draft wire (polyline) through exact global points; "
        "consecutive points are joined by straight segments. A closed wire with "
        "make_face=true becomes a filled planar face usable as an extrusion "
        "profile for part.extrude."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "DraftWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": domain_runtime.vector_schema(
                    "One exact global vertex of the polyline in mm."
                ),
                "minItems": 2,
                "description": (
                    "Ordered vertices of the polyline; consecutive points are "
                    "joined by straight segments. A closed wire needs at least "
                    "3 non-collinear points."
                ),
            },
            "closed": {
                "type": "boolean",
                "description": (
                    "True to join the last point back to the first, forming a "
                    "closed loop."
                ),
            },
            "make_face": {
                "type": "boolean",
                "description": (
                    "True to fill the closed wire into a planar face usable as "
                    "an extrusion profile; requires closed=true and coplanar "
                    "points."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new wire, e.g. 'BaseOutline'.",
            },
        },
        "required": ["points", "closed", "make_face", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    points: list[dict[str, Any]],
    closed: bool,
    make_face: bool,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if not isinstance(points, list) or len(points) < 2:
        return _invalid("points must contain at least 2 vertices.")
    if bool(closed) and len(points) < 3:
        return _invalid("A closed wire needs at least 3 points.")
    if bool(make_face) and not bool(closed):
        return _invalid("make_face=true requires closed=true.")

    def create() -> dict[str, Any]:
        import Draft
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        vectors = [domain_runtime.parse_vector(point) for point in points]
        obj = Draft.make_wire(vectors, closed=bool(closed), face=bool(make_face))
        if obj is None:
            raise RuntimeError("Draft.make_wire did not create an object.")
        obj.Label = clean_label
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": obj.Name,
            "feature_label": obj.Label,
            "feature_type": obj.TypeId,
            "point_count": len(vectors),
            "closed": bool(closed),
            "shape": domain_runtime.shape_summary(obj),
            "feature_state": domain_runtime.feature_state_summary(obj),
        }

    transaction = run_freecad_transaction(
        f"Create Draft wire: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="create_wire")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
