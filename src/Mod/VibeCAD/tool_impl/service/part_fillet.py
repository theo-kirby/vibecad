# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part fillet on exact named edges."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.fillet",
    "description": (
        "Create one native Part fillet that rounds exact named edges of one shaped "
        "object. Finishing operation; apply after the primary form is complete. "
        "Resolve edge names with part.find_subelements first - never guess them. "
        "The source object becomes a hidden child of the fillet result."
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
                "description": "Exact internal name of the object whose edges are filleted.",
            },
            "edge_names": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Exact edge names such as Edge3, from part.find_subelements.",
            },
            "radius_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Fillet radius in mm; must be smaller than the adjacent faces "
                    "can absorb or the fillet fails."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the fillet result.",
            },
        },
        "required": ["object_name", "edge_names", "radius_mm", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    edge_names: list[str],
    radius_mm: float,
    label: str,
) -> dict[str, Any]:
    return run_edge_finish(
        service,
        object_name=object_name,
        edge_names=edge_names,
        size_mm=radius_mm,
        label=label,
        native_type="Part::Fillet",
        operation="fillet",
    )


def run_edge_finish(
    service: Any,
    *,
    object_name: str,
    edge_names: list[str],
    size_mm: float,
    label: str,
    native_type: str,
    operation: str,
) -> dict[str, Any]:
    """Shared implementation for Part fillet and chamfer."""
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    size = float(size_mm)
    if size <= 0:
        return _invalid(f"{operation} size must be positive.")
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Object has no shape geometry: {clean_name}")
    if not isinstance(edge_names, list) or not edge_names:
        return _invalid("edge_names must contain at least one exact edge name.")
    names = [str(name or "").strip() for name in edge_names]
    if len(set(names)) != len(names):
        return _invalid("edge_names cannot contain duplicates.")
    edge_count = len(getattr(shape, "Edges", []) or [])
    indexes: list[int] = []
    for name in names:
        if not name.startswith("Edge"):
            return _invalid(f"Edge names must look like Edge3; got: {name}")
        try:
            index = int(name.removeprefix("Edge"))
        except ValueError:
            return _invalid(f"Edge names must look like Edge3; got: {name}")
        if index < 1 or index > edge_count:
            return _invalid(
                f"{clean_name} has {edge_count} edges; {name} does not exist."
            )
        indexes.append(index)

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        base = active.getObject(clean_name)
        if base is None:
            raise RuntimeError("The object no longer exists.")
        feature = active.addObject(native_type, operation.capitalize())
        feature.Label = clean_label
        feature.Base = base
        feature.Edges = [(index, size, size) for index in indexes]
        active.recompute()
        view = getattr(base, "ViewObject", None)
        if view is not None:
            try:
                view.Visibility = False
            except Exception:
                pass
        return {
            "document": active.Name,
            "feature": feature.Name,
            "feature_label": feature.Label,
            "feature_type": feature.TypeId,
            "source_object": base.Name,
            "edges": names,
            "size_mm": size,
            "shape": domain_runtime.shape_summary(feature),
            "feature_state": domain_runtime.feature_state_summary(feature),
        }

    transaction = run_freecad_transaction(
        f"Create Part {operation}: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation=operation)


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
