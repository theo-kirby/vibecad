# SPDX-License-Identifier: LGPL-2.1-or-later

"""Analyze one exact mesh object for defects that block downstream use."""

from __future__ import annotations

from typing import Any


TOOL_SPEC = {
    "name": "mesh.analyze",
    "description": (
        "Analyze one exact mesh object and report the defects that matter "
        "for repair and BREP conversion: watertightness (solid), "
        "non-manifold edges, self-intersections, inconsistent facet "
        "orientation, invalid points, and the number of separate "
        "components. Run this before mesh.repair to pick repairs and "
        "before meshpart.shape_from_mesh to confirm the mesh is sound."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "MeshWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the mesh object (Mesh::Feature) "
                    "to analyze, as returned by mesh.list_meshes."
                ),
            },
        },
        "required": ["object_name"],
        "additionalProperties": False,
    },
}


def analyze_mesh(mesh: Any) -> dict[str, Any]:
    """Defect and size summary of one Mesh kernel object.

    Shared with mesh.repair for its before/after comparison. Checks that
    fail on this FreeCAD build report ``None`` instead of raising.
    """
    counts = {
        "points": int(getattr(mesh, "CountPoints", 0) or 0),
        "edges": int(getattr(mesh, "CountEdges", 0) or 0),
        "facets": int(getattr(mesh, "CountFacets", 0) or 0),
    }
    defects: dict[str, Any] = {}
    for key, method_name in (
        ("non_manifold_edges", "hasNonManifolds"),
        ("self_intersections", "hasSelfIntersections"),
        ("inconsistent_orientation", "hasNonUniformOrientedFacets"),
        ("invalid_points", "hasInvalidPoints"),
    ):
        try:
            defects[key] = bool(getattr(mesh, method_name)())
        except Exception:
            defects[key] = None
    try:
        is_solid = bool(mesh.isSolid())
    except Exception:
        is_solid = None
    try:
        component_count = int(mesh.countComponents())
    except Exception:
        component_count = None
    summary: dict[str, Any] = {
        "counts": counts,
        "is_solid_watertight": is_solid,
        "component_count": component_count,
        "defects": defects,
        "has_defects": any(bool(value) for value in defects.values()),
    }
    try:
        summary["area_mm2"] = round(float(mesh.Area), 6)
    except Exception:
        pass
    try:
        summary["volume_mm3"] = round(float(mesh.Volume), 6)
    except Exception:
        pass
    return summary


def run(service: Any, object_name: str) -> dict[str, Any]:
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    mesh = getattr(obj, "Mesh", None)
    if mesh is None:
        return _invalid(
            f"Object is not a mesh (no Mesh property): {clean_name}. Use "
            "mesh.list_meshes for mesh names, or meshpart.mesh_from_shape "
            "to create a mesh from a shaped object."
        )
    try:
        summary = analyze_mesh(mesh)
    except Exception as exc:
        return _invalid(f"Mesh analysis failed: {exc}")
    result: dict[str, Any] = {
        "ok": True,
        "document": doc.Name,
        "object": obj.Name,
        "object_label": obj.Label,
        **summary,
    }
    if summary.get("has_defects"):
        result["next_action"] = (
            "Repair the reported defects with mesh.repair, then re-run "
            "mesh.analyze to confirm."
        )
    elif summary.get("is_solid_watertight") is False:
        result["next_action"] = (
            "The mesh has no listed defects but is not watertight; "
            "mesh.repair with fill_holes may close small openings."
        )
    return result


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
