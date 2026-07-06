# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``assembly.add_component``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': 'Add an existing document object (e.g. a PartDesign Body) to a '
                'native Assembly as a component.',
 'name': 'assembly.add_component',
 'parameters': {'properties': {'assembly_name': {'description': 'Assembly name or label. Defaults to the first assembly in the document.',
                                                 'type': 'string'},
                               'component_name': {'description': 'Object name or label to add.',
                                                  'type': 'string'}},
                'required': ['component_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'AssemblyWorkbench'}


def run(
    service,
    assembly_name: str | None = None,
    component_name: str = "",
) -> dict[str, Any]:
    assembly = service._get_assembly(assembly_name)
    if assembly is None:
        return {"ok": False, "error": "Assembly not found.", "requested": assembly_name}
    component = service._get_document_object(component_name)
    if component is None:
        return {"ok": False, "error": f"Component not found: {component_name}"}
    if component is assembly:
        return {"ok": False, "error": "Cannot add an assembly to itself."}

    def _add_component() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_assembly = service._get_assembly(assembly.Name)
        if target_assembly is None:
            raise RuntimeError(f"Assembly not found: {assembly.Name}")
        target_component = service._get_document_object(component.Name)
        if target_component is None:
            raise RuntimeError(f"Component not found: {component.Name}")
        before_group = list(getattr(target_assembly, "Group", []) or [])
        already_present = target_component in before_group
        if not already_present:
            try:
                target_assembly.addObject(target_component)
            except Exception:
                target_assembly.Group = before_group + [target_component]
        doc.recompute()
        return {
            "document": doc.Name,
            "assembly": target_assembly.Name,
            "assembly_label": getattr(target_assembly, "Label", target_assembly.Name),
            "component": target_component.Name,
            "component_label": getattr(target_component, "Label", target_component.Name),
            "already_present": already_present,
            "components": service._assembly_child_counts(target_assembly)["components"],
            "assembly_summary": domain_runtime.assembly_summary(service),
        }

    transaction = run_freecad_transaction(
        f"Add component {component.Name} to Assembly {assembly.Name}",
        _add_component,
    )
    summary = domain_runtime.assembly_summary(service)
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "assembly": result.get("assembly", getattr(assembly, "Name", None)),
        "assembly_label": result.get("assembly_label", getattr(assembly, "Label", getattr(assembly, "Name", None))),
        "component": result.get("component", getattr(component, "Name", None)),
        "component_label": result.get("component_label", getattr(component, "Label", getattr(component, "Name", None))),
        "already_present": bool(result.get("already_present", False)),
        "components": result.get("components"),
        "assembly_summary": summary,
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "Adding assembly component failed."
        response["recoverable"] = True
        response["next_actions"] = [
            {
                "tool": "assembly.get_assemblies",
                "why": "Inspect available assemblies and current component membership.",
            },
            {
                "tool": "core.get_active_document",
                "why": "Inspect available document object names and labels before retrying.",
            },
        ]
    return response
