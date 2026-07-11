# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run the CalculiX solver on an exact FEM analysis and report results."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "fem.solve",
    "description": (
        "Run the CalculiX solver on one exact FEM analysis and report the "
        "result summary (peak von Mises stress in MPa and peak displacement "
        "in mm for static analyses). Requires the ccx binary; if it is "
        "missing this fails with install instructions. The analysis needs a "
        "material, a generated mesh, and for static analyses at least one "
        "fixed support plus one load."
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
        },
        "required": ["analysis_name"],
        "additionalProperties": False,
    },
}


def run(service: Any, analysis_name: str) -> dict[str, Any]:
    analysis = service._get_fem_analysis(str(analysis_name or "").strip())
    if analysis is None:
        return _invalid(
            f"FEM analysis not found by exact internal name: {analysis_name}. "
            "Call fem.list_analysis for exact names."
        )
    try:
        from femtools import ccxtools  # noqa: F401
    except ImportError:
        return _invalid(
            "The FEM workbench is not available in this FreeCAD build; "
            "analyses cannot be solved."
        )
    solver = _find_solver(analysis)
    if solver is None:
        return _invalid(
            "The analysis has no CalculiX solver. Create the analysis with "
            "fem.create_analysis, which adds one."
        )

    def solve() -> dict[str, Any]:
        import FreeCAD as App
        from femtools import ccxtools

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(analysis.Name)
        if target is None:
            raise RuntimeError("The analysis no longer exists.")
        fea = ccxtools.FemToolsCcx(target, solver)
        fea.update_objects()
        fea.setup_working_dir()
        message = fea.check_prerequisites()
        if message:
            raise RuntimeError(
                "The analysis is not ready to solve: "
                + " ".join(str(message).split())
                + " Fix the missing pieces with fem.add_material, "
                "fem.add_constraint, or fem.mesh_analysis, then run "
                "fem.solve again."
            )
        fea.write_inp_file()
        if not fea.inp_file_name:
            raise RuntimeError(
                "Writing the CalculiX input file failed; check that the "
                "constraints reference existing subelements."
            )
        try:
            ret_code = fea.ccx_run()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{exc} Install CalculiX (package 'calculix-ccx' on most "
                "Linux distributions) or set the ccx binary path in "
                "FreeCAD's FEM preferences (CalculiX page)."
            ) from exc
        if ret_code is None:
            raise RuntimeError(
                "CalculiX did not run; the ccx binary was not found. "
                "Install CalculiX or set its path in FreeCAD's FEM "
                "preferences (CalculiX page)."
            )
        if int(ret_code) != 0:
            stderr = " ".join(str(getattr(fea, "ccx_stderr", "")).split())[:500]
            raise RuntimeError(
                f"CalculiX finished with error code {ret_code}. "
                + (f"Solver output: {stderr} " if stderr else "")
                + "Common causes: no material assigned to all elements, "
                "unconstrained rigid-body motion (add a fixed support), or "
                "a degenerate mesh (re-run fem.mesh_analysis with a smaller "
                "max_element_size_mm)."
            )
        fea.load_results()
        active.recompute()
        return {
            "document": active.Name,
            "analysis": target.Name,
            "solver": solver.Name,
            "analysis_type": str(getattr(solver, "AnalysisType", "")),
            "results": _result_summaries(target),
        }

    transaction = run_freecad_transaction(
        f"Solve FEM analysis: {analysis.Name}",
        solve,
    )
    envelope = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "solve"},
        next_action=(
            "Judge the reported peak stress against the material's yield "
            "strength and the peak displacement against the design's "
            "tolerance; refine the mesh and re-solve to confirm convergence."
        ),
    )
    result = transaction.get("result") if isinstance(transaction, dict) else None
    if envelope.get("ok") and isinstance(result, dict) and not result.get("results"):
        envelope["ok"] = False
        envelope["retry_same_call"] = False
        envelope["error"] = (
            "CalculiX ran but produced no result objects; the solve did not "
            "complete. Check the analysis members with fem.list_analysis."
        )
    return envelope


def _find_solver(analysis: Any) -> Any:
    for member in list(getattr(analysis, "Group", []) or []):
        if "Solver" in str(getattr(member, "TypeId", "")):
            return member
    return None


def _result_summaries(analysis: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for member in list(getattr(analysis, "Group", []) or []):
        try:
            if not member.isDerivedFrom("Fem::FemResultObject"):
                continue
        except Exception:
            continue
        item: dict[str, Any] = {
            "result_object": member.Name,
            "result_label": member.Label,
        }
        von_mises = list(getattr(member, "vonMises", []) or [])
        if von_mises:
            item["von_mises_stress_mpa"] = {
                "min": round(float(min(von_mises)), 4),
                "max": round(float(max(von_mises)), 4),
            }
        displacements = list(getattr(member, "DisplacementLengths", []) or [])
        if displacements:
            item["displacement_mm"] = {
                "min": round(float(min(displacements)), 6),
                "max": round(float(max(displacements)), 6),
            }
        node_numbers = list(getattr(member, "NodeNumbers", []) or [])
        if node_numbers:
            item["node_count"] = len(node_numbers)
        summaries.append(item)
    return summaries


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
