# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run the native assembly solver and report the exact outcome."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "assembly.solve",
    "description": (
        "Run the native solver on one exact assembly, moving every unfixed "
        "component to satisfy the current joints, and report the solver "
        "verdict (solved, over-constrained, conflicting, no grounded "
        "component) plus the resulting component placements. Run this after "
        "editing joints or component placements outside the joint tools."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "AssemblyWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "assembly_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the assembly from assembly.list_structure."
                ),
            },
        },
        "required": ["assembly_name"],
        "additionalProperties": False,
    },
}


def run(service: Any, assembly_name: str) -> dict[str, Any]:
    assembly = _find_assembly(service, assembly_name)
    if assembly is None:
        return _invalid(
            f"Assembly not found by exact internal name: {assembly_name}. "
            "Call assembly.list_structure for exact names."
        )

    def solve() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_assembly = active.getObject(assembly.Name)
        if target_assembly is None:
            raise RuntimeError("The assembly no longer exists.")
        solver_code = int(target_assembly.solve(False))
        active.recompute()
        placements = {}
        for child in list(getattr(target_assembly, "Group", []) or []):
            type_id = str(getattr(child, "TypeId", ""))
            if type_id.startswith("Assembly::") and type_id != "Assembly::AssemblyLink":
                continue
            summary = domain_runtime.placement_summary(child)
            if summary is not None:
                placements[child.Name] = summary
        return {
            "document": active.Name,
            "assembly": target_assembly.Name,
            "solver_code": solver_code,
            "solver_verdict": domain_runtime.assembly_solver_verdict(solver_code),
            "component_placements": placements,
        }

    transaction = run_freecad_transaction(
        f"Solve assembly: {assembly.Name}",
        solve,
    )
    envelope = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "solve"},
        next_action=(
            "Verify component placements with part.measure or a screenshot; "
            "if the verdict is not 'solved', fix the reported joint problem "
            "before adding more joints."
        ),
    )
    result = transaction.get("result") if isinstance(transaction, dict) else None
    if envelope.get("ok") and isinstance(result, dict):
        verdict = str(result.get("solver_verdict") or "")
        envelope["solver_verdict"] = verdict
        envelope["solver_code"] = result.get("solver_code")
        if verdict != "solved":
            envelope["ok"] = False
            envelope["retry_same_call"] = False
            envelope["error"] = (
                f"The assembly solver reported '{verdict}' "
                f"(code {result.get('solver_code')}). " + _solver_hint(verdict)
            )
    return envelope


def _solver_hint(verdict: str) -> str:
    return {
        "no_grounded_component": (
            "Ground one component with assembly.ground_component first."
        ),
        "over_constrained": (
            "Remove or relax a joint; the joints collectively remove more "
            "degrees of freedom than the components have."
        ),
        "conflicting_constraints": (
            "Two or more joints contradict each other; inspect the joints "
            "with assembly.list_structure and delete the wrong one."
        ),
        "redundant_constraints": (
            "The assembly solves but has duplicate constraints; consider "
            "removing the redundant joint."
        ),
        "malformed_constraints": (
            "A joint has unusable references; verify each joint's element "
            "names with assembly.list_structure."
        ),
        "solver_error": (
            "The native solver failed; inspect the joints and component "
            "placements with assembly.list_structure."
        ),
    }.get(verdict, "Inspect the assembly with assembly.list_structure.")


def _find_assembly(service: Any, assembly_name: str) -> Any:
    clean = str(assembly_name or "").strip()
    if not clean:
        return None
    for assembly in service._assembly_objects():
        if assembly.Name == clean:
            return assembly
    return None


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
