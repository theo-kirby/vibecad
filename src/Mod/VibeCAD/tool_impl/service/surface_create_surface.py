# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``surface.create_surface``.

Creates native Surface workbench features (Filling, GeomFillSurface,
Sections) from existing edges, wires, or curve objects so surface-first
modeling is a guided tool path instead of a scripting exercise.
"""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_OPERATIONS = ("filling", "geomfill", "sections")
_FILL_TYPES = ("Stretched", "Coons", "Curved")

TOOL_SPEC = {
    "description": (
        "Create a native Surface workbench feature from existing curves or "
        "edges: operation='geomfill' fills 2-4 boundary curves with a "
        "Stretched/Coons/Curved surface, operation='filling' builds a "
        "constrained N-sided patch from a closed loop of boundary edges, "
        "operation='sections' lofts a surface through 2+ section curves. "
        "Boundaries reference existing document objects (sketches, curves, "
        "or shaped objects) and optional edge subelement names already known "
        "from the source geometry."
    ),
    "name": "surface.create_surface",
    "parameters": {
        "properties": {
            "operation": {
                "description": "One of 'geomfill', 'filling', or 'sections'.",
                "enum": list(_OPERATIONS),
                "type": "string",
            },
            "boundaries": {
                "description": (
                    "Ordered boundary/section references. Each entry names an "
                    "existing object and optionally specific edges of it; "
                    "without edges the object's whole curve/wire is used."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "Existing object name or label.",
                        },
                        "edges": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional edge subelement names, e.g. ['Edge1']."
                            ),
                        },
                    },
                    "required": ["object_name"],
                },
                "type": "array",
            },
            "fill_type": {
                "description": (
                    "geomfill only: surface fill method (default 'Stretched')."
                ),
                "enum": list(_FILL_TYPES),
                "type": "string",
            },
            "label": {"type": "string"},
        },
        "required": ["operation", "boundaries"],
        "type": "object",
    },
    "safety": "SAFE_WRITE",
    "workbench": "SurfaceWorkbench",
}


def _resolve_boundaries(
    service: Any, boundaries: list[dict[str, Any]]
) -> tuple[list[tuple[Any, tuple[str, ...]]], str | None]:
    resolved: list[tuple[Any, tuple[str, ...]]] = []
    for entry in boundaries:
        if not isinstance(entry, dict):
            return [], f"Boundary entries must be objects, got: {entry!r}"
        name = str(entry.get("object_name", "")).strip()
        obj = service._get_document_object(name)
        if obj is None:
            return [], f"Boundary object not found: {name}"
        edges = tuple(
            str(edge).strip() for edge in (entry.get("edges") or []) if str(edge).strip()
        )
        resolved.append((obj, edges or ("",)))
    return resolved, None


def run(
    service,
    operation: str,
    boundaries: list[dict[str, Any]],
    fill_type: str = "Stretched",
    label: str = "VibeCAD Surface",
) -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    if op not in _OPERATIONS:
        return {
            "ok": False,
            "error": f"Unknown operation: {operation!r}. Valid operations: {list(_OPERATIONS)}",
        }
    if not boundaries:
        return {"ok": False, "error": "At least one boundary reference is required."}
    requested_fill = str(fill_type or "Stretched").strip().capitalize()
    if requested_fill not in _FILL_TYPES:
        return {
            "ok": False,
            "error": f"fill_type must be one of {list(_FILL_TYPES)}.",
        }
    if op == "geomfill" and not 2 <= len(boundaries) <= 4:
        return {"ok": False, "error": "geomfill needs 2 to 4 boundary curves."}
    if op == "sections" and len(boundaries) < 2:
        return {"ok": False, "error": "sections needs at least two section curves."}
    resolved, error = _resolve_boundaries(service, boundaries)
    if error:
        return {"ok": False, "error": error}

    def _create() -> dict[str, Any]:
        import FreeCAD as App
        import Surface  # noqa: F401 - registers Surface:: document object types

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        link_sublist = [(obj, list(subs)) for obj, subs in resolved]
        if op == "geomfill":
            feature = doc.addObject("Surface::GeomFillSurface", "VibeCAD_GeomFill")
            feature.BoundaryList = link_sublist
            feature.FillType = requested_fill
        elif op == "filling":
            feature = doc.addObject("Surface::Filling", "VibeCAD_Filling")
            feature.BoundaryEdges = link_sublist
        else:
            feature = doc.addObject("Surface::Sections", "VibeCAD_Sections")
            feature.NSections = link_sublist
        feature.Label = label or "VibeCAD Surface"
        doc.recompute()
        shape = getattr(feature, "Shape", None)
        faces = list(getattr(shape, "Faces", []) or [])
        if shape is None or shape.isNull() or not faces:
            state = list(getattr(feature, "State", []) or [])
            raise RuntimeError(
                f"Surface feature produced no faces (State={state}). "
                "Check that the boundary curves connect end-to-end and are "
                "valid edges or wires."
            )
        return {
            "object": feature.Name,
            "label": feature.Label,
            "type": getattr(feature, "TypeId", ""),
            "operation": op,
            "fill_type": requested_fill if op == "geomfill" else None,
            "boundary_count": len(resolved),
            "face_count": len(faces),
            "area_mm2": round(float(getattr(shape, "Area", 0.0) or 0.0), 3),
            "valid": bool(shape.isValid()),
        }

    transaction = run_freecad_transaction(
        f"Create Surface {op}: {label}",
        _create,
    )
    response: dict[str, Any] = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "surface": domain_runtime.surface_summary(service),
    }
    if transaction.get("ok"):
        response["next_actions"] = [
            {
                "tool": "core.capture_view_screenshot",
                "why": "Visually verify the surface shape and boundary fit.",
            },
        ]
    else:
        response["error"] = transaction.get("error", "Surface creation failed.")
    return response
