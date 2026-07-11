# SPDX-License-Identifier: LGPL-2.1-or-later

"""Set the displayed color and transparency of one document object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "material.set_appearance",
    "description": (
        "Set the displayed shape color and transparency of one named document "
        "object. This changes only how the object is rendered in the 3D view; "
        "it does not assign physical material properties (use "
        "material.apply_material for that). Requires the FreeCAD GUI."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "MaterialWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the object whose appearance to set."
                ),
            },
            "red": {
                "type": "integer",
                "minimum": 0,
                "maximum": 255,
                "description": "Red component of the shape color, 0-255.",
            },
            "green": {
                "type": "integer",
                "minimum": 0,
                "maximum": 255,
                "description": "Green component of the shape color, 0-255.",
            },
            "blue": {
                "type": "integer",
                "minimum": 0,
                "maximum": 255,
                "description": "Blue component of the shape color, 0-255.",
            },
            "transparency_percent": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "Transparency of the shape: 0 is fully opaque, 100 is "
                    "fully transparent."
                ),
            },
        },
        "required": ["object_name", "red", "green", "blue", "transparency_percent"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    red: int,
    green: int,
    blue: int,
    transparency_percent: int,
) -> dict[str, Any]:
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return _invalid(
            "The object has no view representation (FreeCAD is running "
            "without a GUI, or the object is not displayable); appearance "
            f"cannot be set: {clean_name}"
        )

    def apply() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(clean_name)
        if target is None:
            raise RuntimeError("The object no longer exists.")
        view_object = getattr(target, "ViewObject", None)
        if view_object is None:
            raise RuntimeError("The object no longer has a view representation.")
        color = (float(red) / 255.0, float(green) / 255.0, float(blue) / 255.0)
        applied: dict[str, Any] = {}
        if hasattr(view_object, "ShapeColor"):
            view_object.ShapeColor = color
            applied["shape_color"] = {
                "red": int(red),
                "green": int(green),
                "blue": int(blue),
            }
        if hasattr(view_object, "Transparency"):
            view_object.Transparency = int(transparency_percent)
            applied["transparency_percent"] = int(transparency_percent)
        if not applied:
            raise RuntimeError(
                "The object's view exposes neither ShapeColor nor "
                "Transparency; appearance cannot be set on this object type."
            )
        active.recompute()
        return {
            "document": active.Name,
            "object": target.Name,
            "object_label": target.Label,
            "applied": applied,
        }

    transaction = run_freecad_transaction(
        f"Set appearance: {clean_name}",
        apply,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "set_appearance"},
        next_action=("Verify the new appearance with core.capture_view_screenshot."),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
