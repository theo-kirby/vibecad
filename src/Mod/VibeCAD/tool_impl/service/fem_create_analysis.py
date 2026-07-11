# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native FEM analysis container with a CalculiX solver."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_ANALYSIS_TYPES = ("static", "frequency", "thermomech", "check", "buckling")


TOOL_SPEC = {
    "name": "fem.create_analysis",
    "description": (
        "Create one native FEM analysis container (Fem::FemAnalysis) with a "
        "CalculiX solver configured for an exact analysis type. The analysis "
        "starts empty: add a material with fem.add_material, constraints "
        "with fem.add_constraint, and a mesh with fem.mesh_analysis before "
        "running fem.solve."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "FemWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Visible label for the new analysis container.",
            },
            "analysis_type": {
                "type": "string",
                "enum": list(_ANALYSIS_TYPES),
                "description": (
                    "Solver analysis type: 'static' for stress/displacement "
                    "under loads, 'frequency' for natural frequencies, "
                    "'thermomech' for coupled thermal-mechanical, 'check' to "
                    "validate the model without solving, 'buckling' for "
                    "linear buckling factors."
                ),
            },
        },
        "required": ["label", "analysis_type"],
        "additionalProperties": False,
    },
}


def run(service: Any, label: str, analysis_type: str) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    clean_type = str(analysis_type or "").strip()
    if clean_type not in _ANALYSIS_TYPES:
        return _invalid(
            f"Unknown analysis_type: {analysis_type}. "
            f"Choose one of: {', '.join(_ANALYSIS_TYPES)}."
        )
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    try:
        import ObjectsFem
    except ImportError:
        return _invalid(
            "The FEM workbench is not available in this FreeCAD build; "
            "analyses cannot be created."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        analysis = ObjectsFem.makeAnalysis(active, "Analysis")
        analysis.Label = clean_label
        solver = ObjectsFem.makeSolverCalculiXCcxTools(active, "CalculiXCcxTools")
        solver.AnalysisType = clean_type
        solver.WorkingDir = ""
        solver.SplitInputWriter = False
        analysis.addObject(solver)
        active.recompute()
        return {
            "document": active.Name,
            "analysis": analysis.Name,
            "analysis_label": analysis.Label,
            "solver": solver.Name,
            "solver_type": solver.TypeId,
            "analysis_type": clean_type,
        }

    transaction = run_freecad_transaction(
        f"Create FEM analysis: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "create_analysis"},
        next_action=(
            "Add a material with fem.add_material (find its UUID with "
            "material.list_materials), then constraints with "
            "fem.add_constraint, then a mesh with fem.mesh_analysis."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
