# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``assembly.set_component_placement``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from .assembly_common import resolve_existing_component
from . import domain_runtime


TOOL_SPEC = {'description': 'Set the placement of a component inside a native Assembly: '
                'position plus yaw/pitch/roll rotation. For objects outside an '
                'assembly use part.set_placement.',
 'name': 'assembly.set_component_placement',
 'parameters': {'properties': {'assembly_name': {'description': 'Assembly name or label. Defaults to the first assembly in the document.',
                                                 'type': 'string'},
                               'component_name': {'description': 'Component name or label to reposition.',
                                                  'type': 'string'},
                               'pitch_degrees': {'description': 'Rotation about Y axis in degrees.',
                                                 'type': 'number'},
                               'roll_degrees': {'description': 'Rotation about X axis in degrees.',
                                                'type': 'number'},
                               'x': {'description': 'X position in mm.',
                                     'type': 'number'},
                               'y': {'description': 'Y position in mm.',
                                     'type': 'number'},
                               'yaw_degrees': {'description': 'Rotation about Z axis in degrees.',
                                               'type': 'number'},
                               'z': {'description': 'Z position in mm.',
                                     'type': 'number'}},
                'required': ['component_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'AssemblyWorkbench'}


def run(
    service,
    component_name: str,
    assembly_name: str | None = None,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    yaw_degrees: float = 0.0,
    pitch_degrees: float = 0.0,
    roll_degrees: float = 0.0,
) -> dict[str, Any]:
    assembly = service._get_assembly(assembly_name)
    if assembly is None:
        return {"ok": False, "error": "Assembly not found.", "requested": assembly_name}
    resolved = resolve_existing_component(service, assembly, component_name)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error") or f"Component not found: {component_name}",
            "component_resolution": resolved.get("resolution"),
            "recoverable": True,
            "next_actions": [
                {
                    "tool": "assembly.add_component",
                    "arguments": {
                        "assembly_name": getattr(assembly, "Name", None),
                        "component_name": component_name,
                    },
                    "why": "Add the component to the assembly before positioning it.",
                }
            ],
        }
    component = resolved["object"]
    if not hasattr(component, "Placement"):
        return {"ok": False, "error": f"Component has no Placement property: {component_name}"}

    def _set_placement() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_assembly = service._get_assembly(assembly.Name)
        if target_assembly is None:
            raise RuntimeError(f"Assembly not found: {assembly.Name}")
        target_resolved = resolve_existing_component(service, target_assembly, component.Name)
        if not target_resolved.get("ok"):
            raise RuntimeError(target_resolved.get("error") or f"Component not found: {component.Name}")
        target_component = target_resolved["object"]
        rotation = (
            App.Rotation(App.Vector(0, 0, 1), float(yaw_degrees))
            * App.Rotation(App.Vector(0, 1, 0), float(pitch_degrees))
            * App.Rotation(App.Vector(1, 0, 0), float(roll_degrees))
        )
        target_component.Placement = App.Placement(
            App.Vector(float(x), float(y), float(z)),
            rotation,
        )
        doc.recompute()
        actual = target_component.Placement
        euler = actual.Rotation.toEuler()
        return {
            "document": doc.Name,
            "assembly": target_assembly.Name,
            "assembly_label": getattr(target_assembly, "Label", target_assembly.Name),
            "component": target_component.Name,
            "component_label": getattr(target_component, "Label", target_component.Name),
            "component_type": getattr(target_component, "TypeId", ""),
            "component_resolution": resolved.get("resolution"),
            "placement": {
                "x": float(actual.Base.x),
                "y": float(actual.Base.y),
                "z": float(actual.Base.z),
            },
            "rotation_degrees": {
                "yaw": float(euler[0]),
                "pitch": float(euler[1]),
                "roll": float(euler[2]),
            },
            "assembly_summary": domain_runtime.assembly_summary(service),
        }

    transaction = run_freecad_transaction(
        f"Set assembly component placement: {component.Name}",
        _set_placement,
    )
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "assembly": result.get("assembly", getattr(assembly, "Name", None)),
        "component": result.get("component", getattr(component, "Name", None)),
        "component_type": result.get("component_type", getattr(component, "TypeId", None)),
        "component_resolution": result.get("component_resolution", resolved.get("resolution")),
        "placement": result.get("placement"),
        "rotation_degrees": result.get("rotation_degrees"),
        "assembly_summary": domain_runtime.assembly_summary(service),
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "Setting assembly component placement failed."
        response["recoverable"] = True
    return response
