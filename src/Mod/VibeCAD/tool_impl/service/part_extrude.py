# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part extrusion from an exact profile object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.extrude",
    "description": (
        "Create one native Part extrusion from an exact named 2D profile object "
        "(a sketch, Draft wire, or planar face). The profile becomes a child of "
        "the result and stays parametric. Closed profiles can produce solids; "
        "open profiles produce shells."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "profile_object_name": {
                "type": "string",
                "description": "Exact internal name of the 2D profile object.",
            },
            "direction": domain_runtime.vector_schema(
                "Extrusion direction as a global vector; it is normalized, so only "
                "the direction matters.",
                units=None,
            ),
            "length_forward_mm": {
                "type": "number",
                "minimum": 0,
                "description": "Extrusion distance along the direction in mm.",
            },
            "length_reverse_mm": {
                "type": "number",
                "minimum": 0,
                "description": (
                    "Additional extrusion distance opposite the direction in mm; "
                    "0 to extrude one way only."
                ),
            },
            "solid": {
                "type": "boolean",
                "description": (
                    "true caps closed profiles into a solid; false leaves an open "
                    "shell. Requires a closed profile when true."
                ),
            },
            "symmetric": {
                "type": "boolean",
                "description": (
                    "true centers the total length on the profile plane and ignores "
                    "length_reverse_mm; false extrudes forward from the profile."
                ),
            },
            "taper_angle_degrees": {
                "type": "number",
                "minimum": -80,
                "maximum": 80,
                "description": (
                    "Draft angle applied along the extrusion in degrees; 0 for "
                    "straight walls."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new extrusion.",
            },
        },
        "required": [
            "profile_object_name",
            "direction",
            "length_forward_mm",
            "length_reverse_mm",
            "solid",
            "symmetric",
            "taper_angle_degrees",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    profile_object_name: str,
    direction: dict[str, Any],
    length_forward_mm: float,
    length_reverse_mm: float,
    solid: bool,
    symmetric: bool,
    taper_angle_degrees: float,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    profile_name = str(profile_object_name or "").strip()
    doc = service._active_document()
    profile = doc.getObject(profile_name) if doc is not None and profile_name else None
    if profile is None:
        return _invalid(
            f"Profile object not found by exact internal name: {profile_object_name}"
        )
    shape = getattr(profile, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Profile object has no shape geometry: {profile_name}")
    forward = float(length_forward_mm)
    reverse = float(length_reverse_mm)
    if forward <= 0 and reverse <= 0:
        return _invalid(
            "At least one of length_forward_mm or length_reverse_mm must be positive."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(profile_name)
        if base is None:
            raise RuntimeError("The profile object no longer exists.")
        vector = domain_runtime.parse_vector(direction)
        if float(vector.Length) <= 1e-9:
            raise RuntimeError("direction must be a non-zero vector.")
        extrusion = active.addObject("Part::Extrusion", "Extrude")
        extrusion.Label = clean_label
        extrusion.Base = base
        extrusion.DirMode = "Custom"
        extrusion.Dir = vector
        extrusion.LengthFwd = forward
        extrusion.LengthRev = reverse
        extrusion.Solid = bool(solid)
        extrusion.Symmetric = bool(symmetric)
        extrusion.TaperAngle = float(taper_angle_degrees)
        active.recompute()
        view = getattr(base, "ViewObject", None)
        if view is not None:
            try:
                view.Visibility = False
            except Exception:
                pass
        return {
            "document": active.Name,
            "feature": extrusion.Name,
            "feature_label": extrusion.Label,
            "feature_type": extrusion.TypeId,
            "profile_object": base.Name,
            "shape": domain_runtime.shape_summary(extrusion),
            "feature_state": domain_runtime.feature_state_summary(extrusion),
        }

    transaction = run_freecad_transaction(
        f"Create Part extrusion: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="extrude")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
