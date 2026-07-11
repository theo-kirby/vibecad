# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Surface blend between exact boundary edges."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime
from .surface_fill import (
    CURVE_REF_ITEM_SCHEMA,
    build_link_sub_list,
    validate_curve_refs,
)


FILL_STYLE_TO_NATIVE = {
    "stretch": "Stretch",
    "coons": "Coons",
    "curved": "Curved",
}


TOOL_SPEC = {
    "name": "surface.blend",
    "description": (
        "Create one native Surface blend (GeomFillSurface) spanning two, three, "
        "or four exact boundary edges. Simpler and more predictable than "
        "surface.fill when the boundary is a small set of edges; use "
        "surface.fill for longer closed loops. Resolve edge names with "
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
                "minItems": 2,
                "maxItems": 4,
                "description": (
                    "Two to four boundary edge references the blend surface "
                    "spans between."
                ),
            },
            "fill_style": {
                "type": "string",
                "enum": ["stretch", "coons", "curved"],
                "description": (
                    "Surface interior style: 'stretch' is the flattest "
                    "interior, 'coons' is a balanced rounded interior, "
                    "'curved' is the most rounded interior."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new blend surface.",
            },
        },
        "required": ["boundary_edges", "fill_style", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    boundary_edges: list[dict[str, Any]],
    fill_style: str,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    native_style = FILL_STYLE_TO_NATIVE.get(str(fill_style or "").strip())
    if native_style is None:
        allowed = ", ".join(sorted(FILL_STYLE_TO_NATIVE))
        return _invalid(f"fill_style must be one of: {allowed}.")
    refs, error = validate_curve_refs(service, boundary_edges, "boundary_edges")
    if error is not None:
        return _invalid(error)
    if not 2 <= len(refs) <= 4:
        return _invalid("boundary_edges must contain two to four references.")

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        blend = active.addObject("Surface::GeomFillSurface", "SurfaceBlend")
        blend.Label = clean_label
        blend.BoundaryList = build_link_sub_list(active, refs)
        blend.FillType = native_style
        active.recompute()
        return {
            "document": active.Name,
            "feature": blend.Name,
            "feature_label": blend.Label,
            "feature_type": blend.TypeId,
            "fill_style": str(fill_style),
            "boundary_edges": [
                {"object_name": name, "edge_name": edge} for name, edge in refs
            ],
            "shape": domain_runtime.shape_summary(blend),
            "feature_state": domain_runtime.feature_state_summary(blend),
        }

    transaction = run_freecad_transaction(
        f"Create surface blend: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="surface_blend")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
