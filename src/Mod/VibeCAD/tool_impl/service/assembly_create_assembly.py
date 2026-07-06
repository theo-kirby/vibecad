# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``assembly.create_assembly``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': 'Create a native Assembly container for positioning multiple '
                'components together, optionally adding existing objects at creation.',
 'name': 'assembly.create_assembly',
 'parameters': {'properties': {'component_names': {'description': 'Existing object names or labels to add as components.',
                                                   'items': {'type': 'string'},
                                                   'type': 'array'},
                               'label': {'type': 'string'}},
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'AssemblyWorkbench'}


def run(
    service,
    label: str = "VibeCAD Assembly",
    component_names: list[str] | None = None,
) -> dict[str, Any]:
    def _create_assembly() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument or App.newDocument()
        assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
        assembly.Label = label
        assembly.Type = "Assembly"
        joint_group = assembly.newObject("Assembly::JointGroup", "Joints")
        added = []
        missing = []
        for component_name in component_names or []:
            component = doc.getObject(str(component_name))
            if component is None:
                component = next(
                    (
                        obj
                        for obj in doc.Objects
                        if getattr(obj, "Label", None) == str(component_name)
                    ),
                    None,
                )
            if component is None:
                missing.append(str(component_name))
                continue
            try:
                assembly.addObject(component)
            except Exception:
                group = list(getattr(assembly, "Group", []) or [])
                if component not in group:
                    assembly.Group = group + [component]
            added.append(component.Name)
        doc.recompute()
        return {
            "document": doc.Name,
            "assembly": assembly.Name,
            "label": assembly.Label,
            "type": assembly.TypeId,
            "joint_group": joint_group.Name,
            "joint_group_type": joint_group.TypeId,
            "components_added": added,
            "missing_components": missing,
            "assembly_summary": domain_runtime.assembly_summary(service),
        }

    transaction = run_freecad_transaction(
        f"Create Assembly with {len(component_names or [])} components",
        _create_assembly,
    )
    summary = domain_runtime.assembly_summary(service)
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "assembly": result.get("assembly"),
        "assembly_label": result.get("label"),
        "components_added": result.get("components_added", []),
        "missing_components": result.get("missing_components", []),
        "assembly_summary": summary,
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "Assembly creation failed."
        response["recoverable"] = True
        response["next_actions"] = [
            {
                "tool": "core.get_active_document",
                "why": "Inspect existing objects before retrying assembly creation.",
            },
            {
                "tool": "assembly.get_assemblies",
                "why": "Inspect current Assembly objects and component counts.",
            },
        ]
    return response
