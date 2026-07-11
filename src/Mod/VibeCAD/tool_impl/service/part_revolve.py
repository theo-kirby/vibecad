# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part revolution from an exact profile object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.revolve",
    "description": (
        "Create one native Part revolution by sweeping an exact named 2D profile "
        "object around a global axis. The profile becomes a child of the result and "
        "stays parametric. The profile must not cross the axis."
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
            "axis_point": domain_runtime.vector_schema(
                "A global point on the revolution axis in mm."
            ),
            "axis_direction": domain_runtime.vector_schema(
                "Direction of the revolution axis; only the direction matters.",
                units=None,
            ),
            "angle_degrees": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 360,
                "description": "Sweep angle in degrees; 360 for a full revolution.",
            },
            "solid": {
                "type": "boolean",
                "description": (
                    "true caps a closed profile into a solid; false leaves an open "
                    "shell."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new revolution.",
            },
        },
        "required": [
            "profile_object_name",
            "axis_point",
            "axis_direction",
            "angle_degrees",
            "solid",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    profile_object_name: str,
    axis_point: dict[str, Any],
    axis_direction: dict[str, Any],
    angle_degrees: float,
    solid: bool,
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

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(profile_name)
        if base is None:
            raise RuntimeError("The profile object no longer exists.")
        axis_vector = domain_runtime.parse_vector(axis_direction)
        if float(axis_vector.Length) <= 1e-9:
            raise RuntimeError("axis_direction must be a non-zero vector.")
        revolution = active.addObject("Part::Revolution", "Revolve")
        revolution.Label = clean_label
        revolution.Source = base
        revolution.Base = domain_runtime.parse_vector(axis_point)
        revolution.Axis = axis_vector
        revolution.Angle = float(angle_degrees)
        revolution.Solid = bool(solid)
        active.recompute()
        view = getattr(base, "ViewObject", None)
        if view is not None:
            try:
                view.Visibility = False
            except Exception:
                pass
        return {
            "document": active.Name,
            "feature": revolution.Name,
            "feature_label": revolution.Label,
            "feature_type": revolution.TypeId,
            "profile_object": base.Name,
            "shape": domain_runtime.shape_summary(revolution),
            "feature_state": domain_runtime.feature_state_summary(revolution),
        }

    transaction = run_freecad_transaction(
        f"Create Part revolution: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="revolve")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
