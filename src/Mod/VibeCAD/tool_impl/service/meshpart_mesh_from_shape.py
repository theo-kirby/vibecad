# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one mesh object by tessellating an exact shaped object."""

from __future__ import annotations

from math import radians
from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime
from .mesh_analyze import analyze_mesh


TOOL_SPEC = {
    "name": "meshpart.mesh_from_shape",
    "description": (
        "Create one mesh object (Mesh::Feature) by tessellating an exact "
        "shaped BREP object. The source object is unchanged and stays in the "
        "document; the mesh is a triangle snapshot suitable for export or "
        "mesh analysis, not for parametric modeling. Smaller deflection "
        "values give finer, heavier meshes."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "MeshPartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "source_object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the shaped object (Part::Feature "
                    "or derived) to tessellate."
                ),
            },
            "linear_deflection_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Maximum allowed distance in mm between the mesh and the "
                    "exact surface; 0.1 suits most parts, smaller is finer."
                ),
            },
            "angular_deflection_degrees": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 90,
                "description": (
                    "Maximum allowed angle in degrees between adjacent mesh "
                    "facets on curved surfaces; 28.5 is the FreeCAD default, "
                    "smaller is finer."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new mesh object.",
            },
        },
        "required": [
            "source_object_name",
            "linear_deflection_mm",
            "angular_deflection_degrees",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    source_object_name: str,
    linear_deflection_mm: float,
    angular_deflection_degrees: float,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    clean_name = str(source_object_name or "").strip()
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(
            f"Object not found by exact internal name: {source_object_name}"
        )
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(
            f"Object has no shape geometry to tessellate: {clean_name}. "
            "meshpart.mesh_from_shape needs a shaped BREP object; for "
            "existing meshes use mesh.analyze."
        )
    try:
        import MeshPart
    except ImportError:
        return _invalid(
            "The MeshPart module is not available in this FreeCAD build; "
            "shapes cannot be tessellated."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        source = active.getObject(clean_name)
        if source is None:
            raise RuntimeError("The source object no longer exists.")
        mesh = MeshPart.meshFromShape(
            Shape=source.Shape,
            LinearDeflection=float(linear_deflection_mm),
            AngularDeflection=radians(float(angular_deflection_degrees)),
            Relative=False,
        )
        feature = active.addObject("Mesh::Feature", "Mesh")
        feature.Label = clean_label
        feature.Mesh = mesh
        active.recompute()
        return {
            "document": active.Name,
            "object": feature.Name,
            "object_label": feature.Label,
            "source_object": source.Name,
            "mesh": analyze_mesh(feature.Mesh),
        }

    transaction = run_freecad_transaction(
        f"Mesh from shape: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "mesh_from_shape"},
        next_action=(
            "Check the returned facet count: refine deflection if too coarse, "
            "or continue with mesh.analyze / export."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
