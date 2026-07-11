# SPDX-License-Identifier: LGPL-2.1-or-later

"""Ground one assembly component so the solver treats it as fixed."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "assembly.ground_component",
    "description": (
        "Ground one exact component of an assembly, permanently fixing its "
        "current position so the solver positions everything else relative to "
        "it. Every assembly needs at least one grounded component before "
        "assembly.solve can succeed; ground the chassis/base part first."
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
            "component_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the component (inside the assembly) "
                    "to fix in place."
                ),
            },
        },
        "required": ["assembly_name", "component_name"],
        "additionalProperties": False,
    },
}


def run(service: Any, assembly_name: str, component_name: str) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    assembly = _find_assembly(service, assembly_name)
    if assembly is None:
        return _invalid(
            f"Assembly not found by exact internal name: {assembly_name}. "
            "Call assembly.list_structure for exact names."
        )
    clean_component = str(component_name or "").strip()
    component = doc.getObject(clean_component) if clean_component else None
    if component is None:
        return _invalid(f"Component not found by exact internal name: {component_name}")
    group_names = {
        getattr(child, "Name", None)
        for child in list(getattr(assembly, "Group", []) or [])
    }
    if clean_component not in group_names:
        return _invalid(
            f"Object {clean_component} is not a child of assembly "
            f"{assembly.Name}. Insert it first with assembly.insert_component."
        )
    for joint in service._assembly_joint_objects(assembly):
        grounded = getattr(joint, "ObjectToGround", None)
        if grounded is not None and getattr(grounded, "Name", None) == clean_component:
            return _invalid(
                f"Component {clean_component} is already grounded by joint "
                f"{joint.Name}.",
                grounded_joint=joint.Name,
            )

    def create() -> dict[str, Any]:
        import FreeCAD as App
        import JointObject

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_assembly = active.getObject(assembly.Name)
        target = active.getObject(clean_component)
        if target_assembly is None or target is None:
            raise RuntimeError("The assembly or component no longer exists.")
        joint_group = domain_runtime.assembly_joint_group(target_assembly)
        ground = joint_group.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, target)
        active.recompute()
        return {
            "document": active.Name,
            "assembly": target_assembly.Name,
            "grounded_joint": ground.Name,
            "grounded_component": target.Name,
            "component_placement": domain_runtime.placement_summary(target),
        }

    transaction = run_freecad_transaction(
        f"Ground assembly component: {clean_component}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "ground_component"},
        next_action=(
            "Relate the remaining components to this grounded one with "
            "assembly.create_joint, then run assembly.solve."
        ),
    )


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
