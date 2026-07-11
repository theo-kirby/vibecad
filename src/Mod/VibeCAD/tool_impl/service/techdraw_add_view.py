# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native TechDraw projected view of exact 3D objects."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_DIRECTION_VECTORS = {
    "front": ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
    "rear": ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "top": ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0)),
    "isometric": ((1.0, -1.0, 1.0), (0.707107, 0.707107, 0.0)),
}


TOOL_SPEC = {
    "name": "techdraw.add_view",
    "description": (
        "Create one native TechDraw projected view of exact named 3D objects "
        "on an exact drawing page. The view is a live projection: it updates "
        "when the source objects change. The result reports the view's "
        "projected edge and vertex names (Edge0, Vertex1, ...) used by "
        "techdraw.add_dimension."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "TechDrawWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "page_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the drawing page from techdraw.list_pages."
                ),
            },
            "source_object_names": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "Exact internal name of one 3D object to project.",
                },
                "minItems": 1,
                "maxItems": 20,
                "description": (
                    "Exact internal names of the 3D objects to project into "
                    "this view; they are projected together as one image."
                ),
            },
            "view_direction": {
                "type": "string",
                "enum": sorted(_DIRECTION_VECTORS),
                "description": (
                    "Standard direction to view the model from: front looks "
                    "along -Y, rear along +Y, left along -X, right along +X, "
                    "top along +Z, bottom along -Z, isometric from the "
                    "(1,-1,1) corner."
                ),
            },
            "x_mm": {
                "type": "number",
                "description": (
                    "Horizontal position of the view center on the page in mm, "
                    "measured from the page's bottom-left corner (A4 landscape "
                    "is 297 wide x 210 high)."
                ),
            },
            "y_mm": {
                "type": "number",
                "description": (
                    "Vertical position of the view center on the page in mm, "
                    "measured from the page's bottom-left corner."
                ),
            },
            "scale": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Drawing scale for this view; 1 is full size, 0.5 is half "
                    "size, 2 doubles the model."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new view, e.g. 'FrontView'.",
            },
        },
        "required": [
            "page_name",
            "source_object_names",
            "view_direction",
            "x_mm",
            "y_mm",
            "scale",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    page_name: str,
    source_object_names: list[str],
    view_direction: str,
    x_mm: float,
    y_mm: float,
    scale: float,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    vectors = _DIRECTION_VECTORS.get(str(view_direction or ""))
    if vectors is None:
        return _invalid(
            "view_direction must be one of: " + ", ".join(sorted(_DIRECTION_VECTORS))
        )
    if float(scale) <= 0:
        return _invalid("scale must be positive.")
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    page = doc.getObject(str(page_name or "").strip())
    if page is None or getattr(page, "TypeId", "") != "TechDraw::DrawPage":
        return _invalid(
            f"Drawing page not found by exact internal name: {page_name}. "
            "Call techdraw.list_pages for exact names."
        )
    if not isinstance(source_object_names, list) or not source_object_names:
        return _invalid("source_object_names must be a non-empty array.")
    sources: list[str] = []
    for raw_name in source_object_names:
        name = str(raw_name or "").strip()
        source = doc.getObject(name) if name else None
        if source is None:
            return _invalid(
                f"Source object not found by exact internal name: {raw_name}"
            )
        shape = getattr(source, "Shape", None)
        if shape is None or shape.isNull():
            return _invalid(f"Source object has no shape geometry: {name}")
        sources.append(name)

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_page = active.getObject(page.Name)
        if target_page is None:
            raise RuntimeError("The drawing page no longer exists.")
        view = active.addObject("TechDraw::DrawViewPart", "View")
        view.Label = clean_label
        target_page.addView(view)
        view.Source = [active.getObject(name) for name in sources]
        direction, x_direction = vectors
        view.Direction = App.Vector(*direction)
        view.XDirection = App.Vector(*x_direction)
        view.ScaleType = "Custom"
        view.Scale = float(scale)
        view.X = float(x_mm)
        view.Y = float(y_mm)
        active.recompute()
        edge_count = None
        vertex_count = None
        try:
            edge_count = len(view.getVisibleEdges())
            vertex_count = len(view.getVisibleVertexes())
        except Exception:
            pass
        return {
            "document": active.Name,
            "page": target_page.Name,
            "view": view.Name,
            "view_label": view.Label,
            "view_direction": view_direction,
            "scale": float(scale),
            "position_mm": {"x": float(x_mm), "y": float(y_mm)},
            "visible_edge_count": edge_count,
            "visible_vertex_count": vertex_count,
            "projected_element_note": (
                "Projected edges are named Edge0..Edge{n-1} and vertices "
                "Vertex0..Vertex{n-1} within this view; use those names in "
                "techdraw.add_dimension."
            ),
        }

    transaction = run_freecad_transaction(
        f"Add TechDraw view: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "add_view"},
        next_action=(
            "Add dimensions with techdraw.add_dimension, or capture a "
            "screenshot to inspect the page."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
