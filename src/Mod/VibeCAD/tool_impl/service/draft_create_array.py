# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Draft array (orthogonal or polar) of an exact object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "draft.create_array",
    "description": (
        "Create one native Draft array of an exact named object: an orthogonal "
        "grid along explicit interval vectors, or a polar ring around an exact "
        "center. The array is one parametric object linked to the source; the "
        "source stays visible and unchanged."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "DraftWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "source_object_name": {
                "type": "string",
                "description": "Exact internal name of the object to replicate.",
            },
            "array": {
                "description": "Array layout; choose exactly one variant.",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "orthogonal",
                                "description": (
                                    "Grid of copies along explicit interval vectors."
                                ),
                            },
                            "interval_x": domain_runtime.vector_schema(
                                "Displacement between consecutive copies along "
                                "the first grid direction in mm."
                            ),
                            "interval_y": domain_runtime.vector_schema(
                                "Displacement between consecutive copies along "
                                "the second grid direction in mm; use {0,0,0} "
                                "with count_y=1 for a single row."
                            ),
                            "count_x": {
                                "type": "integer",
                                "minimum": 1,
                                "description": (
                                    "Copies along interval_x, including the original."
                                ),
                            },
                            "count_y": {
                                "type": "integer",
                                "minimum": 1,
                                "description": (
                                    "Copies along interval_y, including the "
                                    "original; 1 for a single row."
                                ),
                            },
                        },
                        "required": [
                            "type",
                            "interval_x",
                            "interval_y",
                            "count_x",
                            "count_y",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "polar",
                                "description": (
                                    "Ring of copies rotated around a center point."
                                ),
                            },
                            "center": domain_runtime.vector_schema(
                                "Exact global center of rotation in mm; copies "
                                "rotate around the global Z axis through this "
                                "point."
                            ),
                            "count": {
                                "type": "integer",
                                "minimum": 2,
                                "description": (
                                    "Total copies including the original, spread "
                                    "over total_angle_degrees."
                                ),
                            },
                            "total_angle_degrees": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "maximum": 360,
                                "description": (
                                    "Angular span of the ring in degrees; 360 "
                                    "for a full evenly spaced circle."
                                ),
                            },
                        },
                        "required": ["type", "center", "count", "total_angle_degrees"],
                        "additionalProperties": False,
                    },
                ],
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new array, e.g. 'BoltPattern'.",
            },
        },
        "required": ["source_object_name", "array", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    source_object_name: str,
    array: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if not isinstance(array, dict):
        return _invalid("array must be an object.")
    kind = str(array.get("type") or "")
    if kind not in ("orthogonal", "polar"):
        return _invalid("array.type must be orthogonal or polar.")
    source_name = str(source_object_name or "").strip()
    doc = service._active_document()
    source = doc.getObject(source_name) if doc is not None and source_name else None
    if source is None:
        return _invalid(
            f"Source object not found by exact internal name: {source_object_name}"
        )
    if kind == "orthogonal":
        if int(array["count_x"]) * int(array["count_y"]) < 2:
            return _invalid(
                "An orthogonal array needs at least 2 total copies; "
                "increase count_x or count_y."
            )

    def create() -> dict[str, Any]:
        import Draft
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(source_name)
        if base is None:
            raise RuntimeError("The source object no longer exists.")
        if kind == "orthogonal":
            obj = Draft.make_ortho_array(
                base,
                v_x=domain_runtime.parse_vector(array["interval_x"]),
                v_y=domain_runtime.parse_vector(array["interval_y"]),
                v_z=App.Vector(0, 0, 0),
                n_x=int(array["count_x"]),
                n_y=int(array["count_y"]),
                n_z=1,
            )
        else:
            obj = Draft.make_polar_array(
                base,
                number=int(array["count"]),
                angle=float(array["total_angle_degrees"]),
                center=domain_runtime.parse_vector(array["center"]),
            )
        if obj is None:
            raise RuntimeError("Draft array creation did not return an object.")
        obj.Label = clean_label
        active.recompute()
        return {
            "document": active.Name,
            "feature": obj.Name,
            "feature_label": obj.Label,
            "feature_type": obj.TypeId,
            "array_type": kind,
            "source_object": base.Name,
            "shape": domain_runtime.shape_summary(obj),
            "feature_state": domain_runtime.feature_state_summary(obj),
        }

    transaction = run_freecad_transaction(
        f"Create Draft {kind} array: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction, operation=f"create_{kind}_array"
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
