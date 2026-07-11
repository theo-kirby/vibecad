# SPDX-License-Identifier: LGPL-2.1-or-later

"""Extend one exact surface face beyond its current boundary."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "surface.extend",
    "description": (
        "Create one native Surface extension that enlarges an exact named face "
        "beyond its current boundary by a percentage of its size in each "
        "parametric direction. Useful to make a surface big enough for a "
        "boolean or section. Resolve face names with part.find_subelements "
        "first - never guess them."
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
                    "Exact internal name of the object that owns the face."
                ),
            },
            "face_name": {
                "type": "string",
                "description": (
                    "Exact face name such as Face1, from part.find_subelements."
                ),
            },
            "extend_u_percent": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "How far to extend on each side in the surface U "
                    "direction, as a percent of the face size in U; 0 leaves "
                    "U unchanged."
                ),
            },
            "extend_v_percent": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "How far to extend on each side in the surface V "
                    "direction, as a percent of the face size in V; 0 leaves "
                    "V unchanged."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the extended surface.",
            },
        },
        "required": [
            "object_name",
            "face_name",
            "extend_u_percent",
            "extend_v_percent",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    face_name: str,
    extend_u_percent: float,
    extend_v_percent: float,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    extend_u = float(extend_u_percent)
    extend_v = float(extend_v_percent)
    if extend_u <= 0 and extend_v <= 0:
        return _invalid(
            "At least one of extend_u_percent or extend_v_percent must be positive."
        )
    clean_name = str(object_name or "").strip()
    clean_face = str(face_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Object has no shape geometry: {clean_name}")
    face_count = len(getattr(shape, "Faces", []) or [])
    if not clean_face.startswith("Face"):
        return _invalid(f"Face names must look like Face1; got: {face_name}")
    try:
        face_index = int(clean_face.removeprefix("Face"))
    except ValueError:
        return _invalid(f"Face names must look like Face1; got: {face_name}")
    if face_index < 1 or face_index > face_count:
        return _invalid(
            f"{clean_name} has {face_count} faces; {clean_face} does not exist."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(clean_name)
        if base is None:
            raise RuntimeError("The object no longer exists.")
        extend = active.addObject("Surface::Extend", "SurfaceExtend")
        extend.Label = clean_label
        extend.Face = (base, [clean_face])
        extend.ExtendUNeg = extend_u
        extend.ExtendUPos = extend_u
        extend.ExtendVNeg = extend_v
        extend.ExtendVPos = extend_v
        active.recompute()
        return {
            "document": active.Name,
            "feature": extend.Name,
            "feature_label": extend.Label,
            "feature_type": extend.TypeId,
            "source_object": base.Name,
            "face": clean_face,
            "extend_u_percent": extend_u,
            "extend_v_percent": extend_v,
            "shape": domain_runtime.shape_summary(extend),
            "feature_state": domain_runtime.feature_state_summary(extend),
        }

    transaction = run_freecad_transaction(
        f"Extend surface: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="surface_extend")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
