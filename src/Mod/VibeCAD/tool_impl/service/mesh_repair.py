# SPDX-License-Identifier: LGPL-2.1-or-later

"""Repair defects on one exact mesh object with selected repair passes."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime
from .mesh_analyze import analyze_mesh


TOOL_SPEC = {
    "name": "mesh.repair",
    "description": (
        "Repair one exact mesh object by running the selected repair passes "
        "in a safe fixed order (orientation, duplicates, non-manifolds, "
        "degenerations, self-intersections, hole filling). Run mesh.analyze "
        "first and select only the repairs that its report justifies; the "
        "result includes a before/after defect comparison."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "MeshWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the mesh object (Mesh::Feature) "
                    "to repair, as returned by mesh.list_meshes."
                ),
            },
            "harmonize_normals": {
                "type": "boolean",
                "description": (
                    "true reorients inconsistently oriented facets so all "
                    "normals point the same way; false skips this pass."
                ),
            },
            "remove_duplicates": {
                "type": "boolean",
                "description": (
                    "true removes duplicated points and duplicated facets; "
                    "false skips this pass."
                ),
            },
            "remove_non_manifolds": {
                "type": "boolean",
                "description": (
                    "true removes non-manifold edges and points (edges shared "
                    "by more than two facets); false skips this pass."
                ),
            },
            "fix_degenerations": {
                "type": "boolean",
                "description": (
                    "true removes degenerated (zero-area) facets; false skips "
                    "this pass."
                ),
            },
            "fix_self_intersections": {
                "type": "boolean",
                "description": (
                    "true repairs facets that intersect each other; false "
                    "skips this pass."
                ),
            },
            "fill_holes_max_edges": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Fill boundary holes whose outline has at most this many "
                    "edges; 0 skips hole filling. Small values (3-12) close "
                    "pinholes without capping intentional openings."
                ),
            },
        },
        "required": [
            "object_name",
            "harmonize_normals",
            "remove_duplicates",
            "remove_non_manifolds",
            "fix_degenerations",
            "fix_self_intersections",
            "fill_holes_max_edges",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    harmonize_normals: bool,
    remove_duplicates: bool,
    remove_non_manifolds: bool,
    fix_degenerations: bool,
    fix_self_intersections: bool,
    fill_holes_max_edges: int,
) -> dict[str, Any]:
    clean_name = str(object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    if getattr(obj, "Mesh", None) is None:
        return _invalid(
            f"Object is not a mesh (no Mesh property): {clean_name}. Use "
            "mesh.list_meshes for mesh names."
        )
    max_hole_edges = int(fill_holes_max_edges)
    selected = (
        bool(harmonize_normals)
        or bool(remove_duplicates)
        or bool(remove_non_manifolds)
        or bool(fix_degenerations)
        or bool(fix_self_intersections)
        or max_hole_edges > 0
    )
    if not selected:
        return _invalid(
            "No repair selected. Enable at least one repair pass, or set "
            "fill_holes_max_edges above 0."
        )

    def repair() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(clean_name)
        if target is None:
            raise RuntimeError("The mesh object no longer exists.")
        before = analyze_mesh(target.Mesh)
        mesh = target.Mesh.copy()
        applied: list[str] = []
        if harmonize_normals:
            mesh.harmonizeNormals()
            applied.append("harmonize_normals")
        if remove_duplicates:
            mesh.removeDuplicatedPoints()
            mesh.removeDuplicatedFacets()
            applied.append("remove_duplicates")
        if remove_non_manifolds:
            mesh.removeNonManifolds()
            mesh.removeNonManifoldPoints()
            applied.append("remove_non_manifolds")
        if fix_degenerations:
            mesh.fixDegenerations()
            applied.append("fix_degenerations")
        if fix_self_intersections:
            mesh.fixSelfIntersections()
            applied.append("fix_self_intersections")
        if max_hole_edges > 0:
            mesh.fillupHoles(max_hole_edges)
            applied.append(f"fill_holes(max_edges={max_hole_edges})")
        target.Mesh = mesh
        active.recompute()
        return {
            "document": active.Name,
            "object": target.Name,
            "object_label": target.Label,
            "repairs_applied": applied,
            "before": before,
            "after": analyze_mesh(target.Mesh),
        }

    transaction = run_freecad_transaction(
        f"Repair mesh: {clean_name}",
        repair,
    )
    result = (
        transaction.get("result", {})
        if isinstance(transaction.get("result"), dict)
        else {}
    )
    after = result.get("after") if isinstance(result.get("after"), dict) else {}
    next_action = (
        "Re-run mesh.analyze to confirm the defects are resolved."
        if after.get("has_defects")
        else "The mesh reports no remaining defects; it is ready for "
        "meshpart.shape_from_mesh or export."
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "mesh_repair", "repair": result},
        next_action=next_action,
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
