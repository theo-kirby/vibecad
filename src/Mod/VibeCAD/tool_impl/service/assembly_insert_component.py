# SPDX-License-Identifier: LGPL-2.1-or-later

"""Insert one existing object into an assembly as a linked component."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "assembly.insert_component",
    "description": (
        "Insert one existing named object (Part feature, PartDesign Body, or "
        "primitive) into an exact assembly as a new linked component "
        "(App::Link). The source object is not moved or modified; the link is "
        "an independent occurrence that joints and the solver position. Insert "
        "the same source repeatedly for multiple occurrences."
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
                    "Exact internal name of the target assembly from "
                    "assembly.list_structure."
                ),
            },
            "source_object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the existing object to link into "
                    "the assembly."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Visible label for the new component occurrence, e.g. 'Bracket_1'."
                ),
            },
            "position": domain_runtime.vector_schema(
                "Initial global position of the component in mm; the solver "
                "moves unfixed components when joints are solved. Use "
                "{x:0,y:0,z:0} when unsure."
            ),
        },
        "required": ["assembly_name", "source_object_name", "label", "position"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    assembly_name: str,
    source_object_name: str,
    label: str,
    position: dict[str, Any],
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    assembly = _find_assembly(service, assembly_name)
    if assembly is None:
        return _invalid(
            f"Assembly not found by exact internal name: {assembly_name}. "
            "Call assembly.list_structure for exact names."
        )
    source_name = str(source_object_name or "").strip()
    source = doc.getObject(source_name) if source_name else None
    if source is None:
        return _invalid(
            f"Source object not found by exact internal name: {source_object_name}"
        )
    if source is assembly:
        return _invalid("An assembly cannot be inserted into itself.")

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_assembly = active.getObject(assembly.Name)
        base = active.getObject(source_name)
        if target_assembly is None or base is None:
            raise RuntimeError("The assembly or source object no longer exists.")
        link_type = (
            "Assembly::AssemblyLink"
            if base.isDerivedFrom("Assembly::AssemblyObject")
            else "App::Link"
        )
        component = target_assembly.newObject(link_type, base.Name)
        if component is None:
            raise RuntimeError("FreeCAD did not create the component link.")
        component.LinkedObject = base
        component.Label = clean_label
        component.Placement = App.Placement(
            domain_runtime.parse_vector(position), App.Rotation()
        )
        active.recompute()
        return {
            "document": active.Name,
            "assembly": target_assembly.Name,
            "component": component.Name,
            "component_label": component.Label,
            "component_type": component.TypeId,
            "linked_object": base.Name,
            "placement": domain_runtime.placement_summary(component),
        }

    transaction = run_freecad_transaction(
        f"Insert assembly component: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "insert_component"},
        next_action=(
            "Ground the first component with assembly.ground_component, then "
            "relate components with assembly.create_joint using the returned "
            "exact component name."
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
