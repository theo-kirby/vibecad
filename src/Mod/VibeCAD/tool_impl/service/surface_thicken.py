# SPDX-License-Identifier: LGPL-2.1-or-later

"""Thicken one exact surface into a solid with uniform wall thickness."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "surface.thicken",
    "description": (
        "Create one solid by offsetting an exact named surface (shell or face) "
        "by a uniform thickness and filling the gap. This is how a modeled "
        "surface becomes a manufacturable solid wall. The source surface "
        "becomes a hidden child of the result."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "SurfaceWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the surface object to thicken."
                ),
            },
            "thickness_mm": {
                "type": "number",
                "description": (
                    "Wall thickness in mm; positive offsets along the surface "
                    "normal, negative offsets against it. Must be non-zero."
                ),
            },
            "join_style": {
                "type": "string",
                "enum": ["arc", "intersection"],
                "description": (
                    "How offset walls meet at edges: 'arc' rounds the joint, "
                    "'intersection' extends walls to a sharp joint."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the thickened solid.",
            },
        },
        "required": ["object_name", "thickness_mm", "join_style", "label"],
        "additionalProperties": False,
    },
}


JOIN_STYLE_TO_NATIVE = {
    "arc": "Arc",
    "intersection": "Intersection",
}


def run(
    service: Any,
    object_name: str,
    thickness_mm: float,
    join_style: str,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    thickness = float(thickness_mm)
    if abs(thickness) < 1e-9:
        return _invalid("thickness_mm must be non-zero.")
    native_join = JOIN_STYLE_TO_NATIVE.get(str(join_style or "").strip())
    if native_join is None:
        allowed = ", ".join(sorted(JOIN_STYLE_TO_NATIVE))
        return _invalid(f"join_style must be one of: {allowed}.")
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Object has no shape geometry: {clean_name}")
    if not (getattr(shape, "Faces", []) or []):
        return _invalid(
            f"Object has no faces to thicken: {clean_name}. "
            "Thicken needs a surface or shell, not a bare curve."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(clean_name)
        if base is None:
            raise RuntimeError("The object no longer exists.")
        offset = active.addObject("Part::Offset", "Thicken")
        offset.Label = clean_label
        offset.Source = base
        offset.Value = thickness
        offset.Mode = "Skin"
        offset.Join = native_join
        offset.Fill = True
        offset.Intersection = False
        offset.SelfIntersection = False
        active.recompute()
        view = getattr(base, "ViewObject", None)
        if view is not None:
            try:
                view.Visibility = False
            except Exception:
                pass
        return {
            "document": active.Name,
            "feature": offset.Name,
            "feature_label": offset.Label,
            "feature_type": offset.TypeId,
            "source_object": base.Name,
            "thickness_mm": thickness,
            "join_style": str(join_style),
            "shape": domain_runtime.shape_summary(offset),
            "feature_state": domain_runtime.feature_state_summary(offset),
        }

    transaction = run_freecad_transaction(
        f"Thicken surface: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="surface_thicken")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
