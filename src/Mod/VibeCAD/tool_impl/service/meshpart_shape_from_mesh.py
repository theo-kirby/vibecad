# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one BREP shape object from an exact mesh object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "meshpart.shape_from_mesh",
    "description": (
        "Create one BREP shape object (Part::Feature) from an exact mesh "
        "object, so mesh geometry becomes usable by part.* tools (booleans, "
        "measure, subelements). The mesh is unchanged. Every mesh triangle "
        "becomes a planar face, so the result is faceted, not smooth; run "
        "mesh.analyze first — a watertight, defect-free mesh is required "
        "for a valid solid."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "MeshPartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "mesh_object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the mesh object (Mesh::Feature) "
                    "to convert, as returned by mesh.list_meshes."
                ),
            },
            "sewing_tolerance_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Tolerance in mm for sewing neighbouring triangles into "
                    "a connected shell; 0.1 suits most meshes."
                ),
            },
            "make_solid": {
                "type": "boolean",
                "description": (
                    "true converts the sewn shell into a solid (requires a "
                    "watertight mesh); false keeps the result as a shell."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new shape object.",
            },
        },
        "required": [
            "mesh_object_name",
            "sewing_tolerance_mm",
            "make_solid",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    mesh_object_name: str,
    sewing_tolerance_mm: float,
    make_solid: bool,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    clean_name = str(mesh_object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {mesh_object_name}")
    mesh = getattr(obj, "Mesh", None)
    if mesh is None:
        return _invalid(
            f"Object is not a mesh (no Mesh property): {clean_name}. Use "
            "mesh.list_meshes for mesh names."
        )
    try:
        import Part  # noqa: F401
    except ImportError:
        return _invalid(
            "The Part module is not available in this FreeCAD build; meshes "
            "cannot be converted to shapes."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App
        import Part

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        source = active.getObject(clean_name)
        if source is None:
            raise RuntimeError("The mesh object no longer exists.")
        shape = Part.Shape()
        shape.makeShapeFromMesh(source.Mesh.Topology, float(sewing_tolerance_mm))
        if make_solid:
            if not shape.isClosed():
                raise RuntimeError(
                    "The sewn shell is not closed, so no solid can be made. "
                    "Repair the mesh to watertight (mesh.analyze + "
                    "mesh.repair) or set make_solid to false."
                )
            shape = Part.makeSolid(shape)
        feature = active.addObject("Part::Feature", "ShapeFromMesh")
        feature.Label = clean_label
        feature.Shape = shape
        active.recompute()
        return {
            "document": active.Name,
            "feature": feature.Name,
            "feature_label": feature.Label,
            "feature_type": feature.TypeId,
            "mesh_object": source.Name,
            "is_solid": bool(make_solid),
            "shape": domain_runtime.shape_summary(feature),
            "feature_state": domain_runtime.feature_state_summary(feature),
        }

    transaction = run_freecad_transaction(
        f"Shape from mesh: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction,
        operation="shape_from_mesh",
        next_action=(
            "The shape is faceted (one planar face per triangle); verify with "
            "part.measure and expect slow booleans on large meshes."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
