# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Draft circle or circular arc at an exact global position."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "draft.create_circle",
    "description": (
        "Create one native Draft circle or circular arc on the global XY plane "
        "at an exact center and radius. A full circle with make_face=true "
        "becomes a filled planar face usable as an extrusion profile; supply "
        "start/end angles to create an open arc instead."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "DraftWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "center": domain_runtime.vector_schema(
                "Exact global center of the circle in mm."
            ),
            "radius_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Circle radius in mm.",
            },
            "arc": {
                "type": "object",
                "properties": {
                    "start_angle_degrees": {
                        "type": "number",
                        "description": (
                            "Arc start angle in degrees, measured "
                            "counterclockwise from the global +X axis."
                        ),
                    },
                    "end_angle_degrees": {
                        "type": "number",
                        "description": (
                            "Arc end angle in degrees, measured counterclockwise "
                            "from the global +X axis; must differ from "
                            "start_angle_degrees."
                        ),
                    },
                },
                "required": ["start_angle_degrees", "end_angle_degrees"],
                "additionalProperties": False,
                "description": (
                    "Omit for a full circle. Provide both angles to create an "
                    "open circular arc from start to end, counterclockwise."
                ),
            },
            "make_face": {
                "type": "boolean",
                "description": (
                    "True to fill a full circle into a planar face usable as an "
                    "extrusion profile; ignored for arcs, which stay open edges."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new object, e.g. 'BoltCircle'.",
            },
        },
        "required": ["center", "radius_mm", "make_face", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    center: dict[str, Any],
    radius_mm: float,
    make_face: bool,
    label: str,
    arc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    radius = float(radius_mm)
    if radius <= 0:
        return _invalid("radius_mm must be greater than 0.")
    is_arc = isinstance(arc, dict)
    if is_arc:
        start = float(arc["start_angle_degrees"])
        end = float(arc["end_angle_degrees"])
        if abs(end - start) <= 1e-9:
            return _invalid(
                "arc start_angle_degrees and end_angle_degrees must differ."
            )
    else:
        start = 0.0
        end = 0.0

    def create() -> dict[str, Any]:
        import Draft
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        placement = App.Placement(domain_runtime.parse_vector(center), App.Rotation())
        if is_arc:
            obj = Draft.make_circle(
                radius,
                placement=placement,
                face=False,
                startangle=start,
                endangle=end,
            )
        else:
            obj = Draft.make_circle(
                radius,
                placement=placement,
                face=bool(make_face),
            )
        if obj is None:
            raise RuntimeError("Draft.make_circle did not create an object.")
        obj.Label = clean_label
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": obj.Name,
            "feature_label": obj.Label,
            "feature_type": obj.TypeId,
            "radius_mm": radius,
            "is_arc": is_arc,
            "shape": domain_runtime.shape_summary(obj),
            "feature_state": domain_runtime.feature_state_summary(obj),
        }

    kind = "arc" if is_arc else "circle"
    transaction = run_freecad_transaction(
        f"Create Draft {kind}: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation=f"create_{kind}")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
