# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Surface filling patch from exact boundary edges."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


CURVE_REF_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "object_name": {
            "type": "string",
            "description": "Exact internal name of the curve or shaped object.",
        },
        "edge_name": {
            "type": "string",
            "description": (
                "Exact edge name such as Edge2 on that object, from "
                "part.find_subelements; empty string to use every edge of "
                "the object (for single-wire curves such as Draft wires)."
            ),
        },
    },
    "required": ["object_name", "edge_name"],
    "additionalProperties": False,
}


TOOL_SPEC = {
    "name": "surface.fill",
    "description": (
        "Create one native Surface filling patch that covers a closed loop of "
        "exact boundary edges. The referenced edges must connect end-to-end "
        "into one closed loop or the patch fails. Resolve edge names with "
        "part.find_subelements first - never guess them."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "SurfaceWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "boundary_edges": {
                "type": "array",
                "items": CURVE_REF_ITEM_SCHEMA,
                "minItems": 1,
                "description": (
                    "Boundary edge references, in loop order, that together "
                    "form one closed loop."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new surface patch.",
            },
        },
        "required": ["boundary_edges", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    boundary_edges: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    refs, error = validate_curve_refs(service, boundary_edges, "boundary_edges")
    if error is not None:
        return _invalid(error)

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        filling = active.addObject("Surface::Filling", "SurfaceFill")
        filling.Label = clean_label
        filling.BoundaryEdges = build_link_sub_list(active, refs)
        active.recompute()
        return {
            "document": active.Name,
            "feature": filling.Name,
            "feature_label": filling.Label,
            "feature_type": filling.TypeId,
            "boundary_edges": [
                {"object_name": name, "edge_name": edge} for name, edge in refs
            ],
            "shape": domain_runtime.shape_summary(filling),
            "feature_state": domain_runtime.feature_state_summary(filling),
        }

    transaction = run_freecad_transaction(
        f"Create surface fill: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="surface_fill")


def validate_curve_refs(
    service: Any,
    raw_refs: Any,
    param_name: str,
) -> tuple[list[tuple[str, str]], str | None]:
    """Validate curve references against the active document.

    Returns ``(refs, None)`` on success where each ref is an
    ``(object_name, edge_name)`` pair with ``edge_name`` possibly empty,
    or ``([], message)`` on failure.
    """
    doc = service._active_document()
    if doc is None:
        return [], "No active document."
    if not isinstance(raw_refs, list) or not raw_refs:
        return [], f"{param_name} must contain at least one curve reference."
    refs: list[tuple[str, str]] = []
    for entry in raw_refs:
        if not isinstance(entry, dict):
            return [], f"Each {param_name} item must be an object."
        object_name = str(entry.get("object_name") or "").strip()
        edge_name = str(entry.get("edge_name") or "").strip()
        obj = doc.getObject(object_name) if object_name else None
        if obj is None:
            return [], f"Object not found by exact internal name: {object_name}"
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            return [], f"Object has no shape geometry: {object_name}"
        if edge_name:
            edge_count = len(getattr(shape, "Edges", []) or [])
            if not edge_name.startswith("Edge"):
                return [], f"Edge names must look like Edge3; got: {edge_name}"
            try:
                index = int(edge_name.removeprefix("Edge"))
            except ValueError:
                return [], f"Edge names must look like Edge3; got: {edge_name}"
            if index < 1 or index > edge_count:
                return [], (
                    f"{object_name} has {edge_count} edges; {edge_name} does not exist."
                )
        refs.append((object_name, edge_name))
    if len(set(refs)) != len(refs):
        return [], f"{param_name} cannot contain duplicate references."
    return refs, None


def build_link_sub_list(active: Any, refs: list[tuple[str, str]]) -> list[Any]:
    """Build a FreeCAD LinkSubList value from validated curve references."""
    entries: list[Any] = []
    for object_name, edge_name in refs:
        obj = active.getObject(object_name)
        if obj is None:
            raise RuntimeError(f"The object no longer exists: {object_name}")
        if edge_name:
            entries.append((obj, edge_name))
        else:
            entries.append(obj)
    return entries


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
