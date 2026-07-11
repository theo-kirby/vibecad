# SPDX-License-Identifier: LGPL-2.1-or-later

"""Set the exact global placement of one document object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.set_placement",
    "description": (
        "Set the exact global placement (position and rotation) of one named "
        "document object. This replaces the whole placement; read the current one "
        "first if you only want to adjust it. Rotation is axis-angle."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Exact internal name of the object to reposition.",
            },
            "position": domain_runtime.vector_schema(
                "New global position of the object's local origin in mm."
            ),
            "rotation_axis": domain_runtime.vector_schema(
                "Rotation axis; only the direction matters. Use {x:0,y:0,z:1} with "
                "angle 0 for no rotation.",
                units=None,
            ),
            "rotation_angle_degrees": {
                "type": "number",
                "minimum": -360,
                "maximum": 360,
                "description": "Rotation around the axis in degrees; 0 for none.",
            },
        },
        "required": [
            "object_name",
            "position",
            "rotation_axis",
            "rotation_angle_degrees",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    position: dict[str, Any],
    rotation_axis: dict[str, Any],
    rotation_angle_degrees: float,
) -> dict[str, Any]:
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    if not hasattr(obj, "Placement"):
        return _invalid(f"Object has no placement: {clean_name}")

    def apply() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(clean_name)
        if target is None:
            raise RuntimeError("The object no longer exists.")
        axis = domain_runtime.parse_vector(rotation_axis)
        if float(axis.Length) <= 1e-9:
            raise RuntimeError("rotation_axis must be a non-zero vector.")
        before = target.Placement
        placement_before = {
            "position": {
                "x": float(before.Base.x),
                "y": float(before.Base.y),
                "z": float(before.Base.z),
            },
            "rotation_axis": {
                "x": float(before.Rotation.Axis.x),
                "y": float(before.Rotation.Axis.y),
                "z": float(before.Rotation.Axis.z),
            },
            "rotation_angle_degrees": float(before.Rotation.Angle)
            * 180.0
            / 3.141592653589793,
        }
        target.Placement = App.Placement(
            domain_runtime.parse_vector(position),
            App.Rotation(axis, float(rotation_angle_degrees)),
        )
        active.recompute()
        after = target.Placement
        return {
            "document": active.Name,
            "object": target.Name,
            "object_label": target.Label,
            "placement_before": placement_before,
            "placement_after": {
                "position": {
                    "x": float(after.Base.x),
                    "y": float(after.Base.y),
                    "z": float(after.Base.z),
                },
                "rotation_axis": {
                    "x": float(after.Rotation.Axis.x),
                    "y": float(after.Rotation.Axis.y),
                    "z": float(after.Rotation.Axis.z),
                },
                "rotation_angle_degrees": float(after.Rotation.Angle)
                * 180.0
                / 3.141592653589793,
            },
            "shape": domain_runtime.shape_summary(target),
        }

    transaction = run_freecad_transaction(
        f"Set placement: {clean_name}",
        apply,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        next_action=(
            "Verify the new position with part.measure or a screenshot before "
            "depending on it."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
