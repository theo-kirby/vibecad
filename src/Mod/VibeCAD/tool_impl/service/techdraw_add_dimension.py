# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native TechDraw dimension on exact projected view elements."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_NATIVE_TYPES = {
    "length": "Distance",
    "horizontal_length": "DistanceX",
    "vertical_length": "DistanceY",
    "radius": "Radius",
    "diameter": "Diameter",
    "angle": "Angle",
    "angle_3_point": "Angle3Pt",
}


def _references_schema(
    description: str, *, min_items: int, max_items: int
) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "string",
            "description": (
                "Exact projected element name within the view, e.g. 'Edge0' "
                "or 'Vertex3'."
            ),
        },
        "minItems": min_items,
        "maxItems": max_items,
        "description": description,
    }


def _variant(
    kind: str, kind_description: str, references: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {"const": kind, "description": kind_description},
            "references": references,
        },
        "required": ["type", "references"],
        "additionalProperties": False,
    }


TOOL_SPEC = {
    "name": "techdraw.add_dimension",
    "description": (
        "Create one native TechDraw dimension measuring exact projected "
        "elements of one view. Projected elements are named Edge0, Vertex1, "
        "... within the view (indices start at 0 and differ from the 3D "
        "model's names). The dimension stays live: it re-measures when the "
        "model changes. The result reports the measured value in mm or "
        "degrees."
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
            "view_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the view that owns the referenced "
                    "elements, from techdraw.list_pages."
                ),
            },
            "dimension": {
                "description": "What to measure; choose exactly one variant.",
                "oneOf": [
                    _variant(
                        "length",
                        "True length between the references.",
                        _references_schema(
                            "One straight edge, or two vertices, or two "
                            "parallel edges.",
                            min_items=1,
                            max_items=2,
                        ),
                    ),
                    _variant(
                        "horizontal_length",
                        "Length projected onto the page's horizontal axis.",
                        _references_schema(
                            "One straight edge, or two vertices.",
                            min_items=1,
                            max_items=2,
                        ),
                    ),
                    _variant(
                        "vertical_length",
                        "Length projected onto the page's vertical axis.",
                        _references_schema(
                            "One straight edge, or two vertices.",
                            min_items=1,
                            max_items=2,
                        ),
                    ),
                    _variant(
                        "radius",
                        "Radius of one circular or arc edge.",
                        _references_schema(
                            "Exactly one circular or arc edge.",
                            min_items=1,
                            max_items=1,
                        ),
                    ),
                    _variant(
                        "diameter",
                        "Diameter of one circular or arc edge.",
                        _references_schema(
                            "Exactly one circular or arc edge.",
                            min_items=1,
                            max_items=1,
                        ),
                    ),
                    _variant(
                        "angle",
                        "Angle between two straight edges.",
                        _references_schema(
                            "Exactly two straight, non-parallel edges.",
                            min_items=2,
                            max_items=2,
                        ),
                    ),
                    _variant(
                        "angle_3_point",
                        "Angle defined by three vertices; the second vertex "
                        "is the apex.",
                        _references_schema(
                            "Exactly three vertices in order: end, apex, end.",
                            min_items=3,
                            max_items=3,
                        ),
                    ),
                ],
            },
        },
        "required": ["page_name", "view_name", "dimension"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    page_name: str,
    view_name: str,
    dimension: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(dimension, dict):
        return _invalid("dimension must be an object.")
    kind = str(dimension.get("type") or "")
    native_type = _NATIVE_TYPES.get(kind)
    if native_type is None:
        return _invalid(
            "dimension.type must be one of: " + ", ".join(sorted(_NATIVE_TYPES))
        )
    references = dimension.get("references")
    if not isinstance(references, list) or not references:
        return _invalid("dimension.references must be a non-empty array.")
    elements = [str(item or "").strip() for item in references]
    for element in elements:
        if not (element.startswith("Edge") or element.startswith("Vertex")):
            return _invalid(
                f"Unsupported reference element: {element!r}. Use projected "
                "element names like 'Edge0' or 'Vertex3'."
            )
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    page = doc.getObject(str(page_name or "").strip())
    if page is None or getattr(page, "TypeId", "") != "TechDraw::DrawPage":
        return _invalid(
            f"Drawing page not found by exact internal name: {page_name}. "
            "Call techdraw.list_pages for exact names."
        )
    view = doc.getObject(str(view_name or "").strip())
    if view is None or not str(getattr(view, "TypeId", "")).startswith(
        "TechDraw::DrawViewPart"
    ):
        return _invalid(
            f"Projected view not found by exact internal name: {view_name}. "
            "Call techdraw.list_pages for exact names; dimensions attach to "
            "part views, not annotations."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_page = active.getObject(page.Name)
        target_view = active.getObject(view.Name)
        if target_page is None or target_view is None:
            raise RuntimeError("The page or view no longer exists.")
        dim = active.addObject("TechDraw::DrawViewDimension", "Dimension")
        target_page.addView(dim)
        dim.Type = native_type
        dim.MeasureType = "Projected"
        dim.References2D = [(target_view, element) for element in elements]
        active.recompute()
        value = None
        text = None
        try:
            value = float(dim.getRawValue())
        except Exception:
            pass
        try:
            text = str(dim.getText())
        except Exception:
            pass
        state = list(getattr(dim, "State", []) or [])
        return {
            "document": active.Name,
            "page": target_page.Name,
            "view": target_view.Name,
            "dimension": dim.Name,
            "dimension_type": native_type,
            "references": elements,
            "value": value,
            "value_units": "degrees" if "angle" in kind else "mm",
            "display_text": text,
            "up_to_date": "Up-to-date" in state,
        }

    transaction = run_freecad_transaction(
        f"Add TechDraw {kind} dimension",
        create,
    )
    envelope = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": f"add_{kind}_dimension"},
        next_action=(
            "Check the returned value against the model, then add the next "
            "dimension or annotation."
        ),
    )
    result = transaction.get("result") if isinstance(transaction, dict) else None
    if envelope.get("ok") and isinstance(result, dict):
        if not result.get("up_to_date") or result.get("value") is None:
            envelope["ok"] = False
            envelope["retry_same_call"] = False
            envelope["error"] = (
                "The dimension was created but did not compute a value. The "
                "referenced elements probably do not suit this dimension type "
                "(e.g. radius needs a circular edge). The dimension was left "
                "in the document for inspection or deletion."
            )
    return envelope


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
