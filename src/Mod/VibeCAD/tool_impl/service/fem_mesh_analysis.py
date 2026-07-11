# SPDX-License-Identifier: LGPL-2.1-or-later

"""Generate the FEM mesh for an exact analysis by tessellating one shape."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "fem.mesh_analysis",
    "description": (
        "Create a Gmsh FEM mesh object for an exact analysis and run the "
        "Gmsh mesher on one exact shaped object, producing the finite "
        "element mesh the solver needs. Requires the Gmsh binary; if it is "
        "missing this fails with instructions rather than solving anyway. "
        "Re-run after the model geometry changes."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "FemWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "analysis_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the FEM analysis from fem.list_analysis."
                ),
            },
            "source_object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the shaped object to mesh — the "
                    "solid being analyzed (a PartDesign body or Part "
                    "feature), not a triangle mesh."
                ),
            },
            "max_element_size_mm": {
                "type": "number",
                "minimum": 0,
                "description": (
                    "Maximum finite element edge length in mm; 0 lets Gmsh "
                    "choose automatically. Roughly 1/10 of the smallest "
                    "important feature is a sound starting point; smaller "
                    "values give more accurate but slower solves."
                ),
            },
            "element_order": {
                "type": "string",
                "enum": ["1st", "2nd"],
                "description": (
                    "Finite element order: '2nd' (quadratic, the FreeCAD "
                    "default) is markedly more accurate for stress; '1st' "
                    "(linear) meshes and solves faster for rough checks."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new FEM mesh object.",
            },
        },
        "required": [
            "analysis_name",
            "source_object_name",
            "max_element_size_mm",
            "element_order",
            "label",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    analysis_name: str,
    source_object_name: str,
    max_element_size_mm: float,
    element_order: str,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if element_order not in ("1st", "2nd"):
        return _invalid("element_order must be '1st' or '2nd'.")
    if float(max_element_size_mm) < 0:
        return _invalid("max_element_size_mm cannot be negative.")
    analysis = service._get_fem_analysis(str(analysis_name or "").strip())
    if analysis is None:
        return _invalid(
            f"FEM analysis not found by exact internal name: {analysis_name}. "
            "Call fem.list_analysis for exact names."
        )
    clean_source = str(source_object_name or "").strip()
    doc = service._active_document()
    source = doc.getObject(clean_source) if doc is not None and clean_source else None
    if source is None:
        return _invalid(
            f"Object not found by exact internal name: {source_object_name}"
        )
    shape = getattr(source, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(
            f"Object has no shape geometry to mesh: {clean_source}. "
            "fem.mesh_analysis needs a shaped BREP object such as a "
            "PartDesign body or Part feature."
        )
    try:
        import ObjectsFem  # noqa: F401
    except ImportError:
        return _invalid(
            "The FEM workbench is not available in this FreeCAD build; "
            "FEM meshes cannot be created."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App
        import ObjectsFem
        from femmesh import gmshtools

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(analysis.Name)
        if target is None:
            raise RuntimeError("The analysis no longer exists.")
        part_obj = active.getObject(clean_source)
        if part_obj is None:
            raise RuntimeError("The source object no longer exists.")
        mesh_obj = ObjectsFem.makeMeshGmsh(active, "FEMMeshGmsh")
        mesh_obj.Label = clean_label
        mesh_obj.Shape = part_obj
        mesh_obj.ElementOrder = element_order
        if float(max_element_size_mm) > 0:
            mesh_obj.CharacteristicLengthMax = f"{float(max_element_size_mm)} mm"
        target.addObject(mesh_obj)
        try:
            tool = gmshtools.GmshTools(mesh_obj)
            finished = tool.run(blocking=True)
        except gmshtools.GmshError as exc:
            raise RuntimeError(
                f"Gmsh could not run: {exc} Install Gmsh or set its binary "
                "path in FreeCAD's FEM preferences (Gmsh page), then call "
                "fem.mesh_analysis again."
            ) from exc
        fem_mesh = getattr(mesh_obj, "FemMesh", None)
        node_count = int(getattr(fem_mesh, "NodeCount", 0) or 0)
        if not finished or node_count == 0:
            raise RuntimeError(
                "Gmsh ran but produced no mesh nodes. Check that the shape "
                "is a valid solid (part.measure reports volume) and try a "
                "different max_element_size_mm."
            )
        active.recompute()
        return {
            "document": active.Name,
            "analysis": target.Name,
            "mesh_object": mesh_obj.Name,
            "mesh_object_label": mesh_obj.Label,
            "source_object": part_obj.Name,
            "element_order": element_order,
            "node_count": node_count,
            "volume_element_count": int(getattr(fem_mesh, "VolumeCount", 0) or 0),
            "face_element_count": int(getattr(fem_mesh, "FaceCount", 0) or 0),
        }

    transaction = run_freecad_transaction(
        f"Create FEM mesh: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "mesh_analysis"},
        next_action=(
            "Run fem.solve once the analysis has a material and at least "
            "one fixed support plus one load."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
