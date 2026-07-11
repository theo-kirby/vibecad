# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native assembly joint between two exact component references."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_JOINT_TYPE_NATIVE = {
    "fixed": "Fixed",
    "revolute": "Revolute",
    "cylindrical": "Cylindrical",
    "slider": "Slider",
    "ball": "Ball",
    "distance": "Distance",
}


def _reference_schema(which: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            f"The {which} joint connector: an exact component and the exact "
            "subelement on it to attach to."
        ),
        "properties": {
            "component_name": {
                "type": "string",
                "description": (
                    f"Exact internal name of the {which} component inside the "
                    "assembly (from assembly.list_structure), not the linked "
                    "source object."
                ),
            },
            "element": {
                "type": "string",
                "description": (
                    "Exact subelement on that component to attach the joint "
                    "connector to, e.g. 'Face3' or 'Edge5' from "
                    "part.find_subelements. The connector is placed at the "
                    "element's natural center (a cylindrical face yields its "
                    "axis). Use an empty string to attach at the component's "
                    "local origin."
                ),
            },
        },
        "required": ["component_name", "element"],
        "additionalProperties": False,
    }


TOOL_SPEC = {
    "name": "assembly.create_joint",
    "description": (
        "Create one native assembly joint connecting two exact component "
        "references, then run the solver so unfixed components move to "
        "satisfy it. Joint types remove degrees of freedom: fixed locks all "
        "six, revolute leaves one rotation, cylindrical leaves rotation plus "
        "translation along one axis, slider leaves one translation, ball "
        "leaves all three rotations, distance holds a set separation. Ground "
        "one component first or the solver cannot run."
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
            "reference1": _reference_schema("first"),
            "reference2": _reference_schema("second"),
            "joint": {
                "description": "Joint behavior; choose exactly one variant.",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "fixed",
                                "description": (
                                    "Rigidly locks the two references "
                                    "together; use planar faces or vertices "
                                    "as references."
                                ),
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "revolute",
                                "description": (
                                    "Hinge: one rotation remains around the "
                                    "shared axis; use circular edges or "
                                    "cylindrical faces as references."
                                ),
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "cylindrical",
                                "description": (
                                    "Pin in a bore: rotation plus translation "
                                    "along the shared axis remain; use "
                                    "cylindrical faces as references."
                                ),
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "slider",
                                "description": (
                                    "Prismatic: one translation along the "
                                    "shared axis remains, no rotation; use "
                                    "linear edges or planar faces as "
                                    "references."
                                ),
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "ball",
                                "description": (
                                    "Ball-and-socket: all three rotations "
                                    "remain around the shared point; use "
                                    "vertices or spherical faces as "
                                    "references."
                                ),
                            },
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "distance",
                                "description": (
                                    "Holds the two references at a fixed "
                                    "separation without locking orientation."
                                ),
                            },
                            "distance_mm": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Separation to maintain between the two "
                                    "references in mm."
                                ),
                            },
                        },
                        "required": ["type", "distance_mm"],
                        "additionalProperties": False,
                    },
                ],
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new joint, e.g. 'HingePin'.",
            },
        },
        "required": ["assembly_name", "reference1", "reference2", "joint", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    assembly_name: str,
    reference1: dict[str, Any],
    reference2: dict[str, Any],
    joint: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if not isinstance(joint, dict):
        return _invalid("joint must be an object.")
    kind = str(joint.get("type") or "")
    native_type = _JOINT_TYPE_NATIVE.get(kind)
    if native_type is None:
        return _invalid(
            "joint.type must be one of: " + ", ".join(sorted(_JOINT_TYPE_NATIVE))
        )
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    assembly = _find_assembly(service, assembly_name)
    if assembly is None:
        return _invalid(
            f"Assembly not found by exact internal name: {assembly_name}. "
            "Call assembly.list_structure for exact names."
        )
    parsed_refs = []
    for key, reference in (("reference1", reference1), ("reference2", reference2)):
        if not isinstance(reference, dict):
            return _invalid(f"{key} must be an object.")
        component_name = str(reference.get("component_name") or "").strip()
        component = doc.getObject(component_name) if component_name else None
        if component is None:
            return _invalid(
                f"{key}.component_name not found by exact internal name: "
                f"{reference.get('component_name')}"
            )
        element = str(reference.get("element") or "").strip()
        parsed_refs.append((component_name, element))
    if parsed_refs[0][0] == parsed_refs[1][0]:
        return _invalid(
            "reference1 and reference2 must be on two different components; "
            "a joint between a component and itself does nothing."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App
        import JointObject

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target_assembly = active.getObject(assembly.Name)
        if target_assembly is None:
            raise RuntimeError("The assembly no longer exists.")
        refs = []
        for component_name, element in parsed_refs:
            component = active.getObject(component_name)
            if component is None:
                raise RuntimeError(f"Component no longer exists: {component_name}")
            refs.append([component, [element, element]])
        joint_group = domain_runtime.assembly_joint_group(target_assembly)
        joint_obj = joint_group.newObject("App::FeaturePython", "Joint")
        type_index = JointObject.JointTypes.index(native_type)
        JointObject.Joint(joint_obj, type_index)
        joint_obj.Label = clean_label
        if kind == "distance":
            joint_obj.Distance = float(joint["distance_mm"])
        joint_obj.Proxy.setJointConnectors(joint_obj, refs)
        solver_code = int(target_assembly.solve(False))
        active.recompute()
        return {
            "document": active.Name,
            "assembly": target_assembly.Name,
            "joint": joint_obj.Name,
            "joint_label": joint_obj.Label,
            "joint_type": native_type,
            "solver_code": solver_code,
            "solver_verdict": domain_runtime.assembly_solver_verdict(solver_code),
            "component_placements": {
                component_name: domain_runtime.placement_summary(
                    active.getObject(component_name)
                )
                for component_name, _ in parsed_refs
            },
        }

    transaction = run_freecad_transaction(
        f"Create assembly {kind} joint: {clean_label}",
        create,
    )
    envelope = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": f"create_{kind}_joint"},
        next_action=(
            "Check solver_verdict and the returned component placements, then "
            "add the next joint or run assembly.solve."
        ),
    )
    result = transaction.get("result") if isinstance(transaction, dict) else None
    if envelope.get("ok") and isinstance(result, dict):
        verdict = str(result.get("solver_verdict") or "")
        if verdict != "solved":
            envelope["ok"] = False
            envelope["retry_same_call"] = False
            envelope["error"] = (
                f"The joint was created but the assembly solver reported "
                f"'{verdict}' (code {result.get('solver_code')}). "
                + _solver_hint(verdict)
                + " The joint was left in the document for inspection or deletion."
            )
    return envelope


def _solver_hint(verdict: str) -> str:
    return {
        "no_grounded_component": (
            "Ground one component with assembly.ground_component first."
        ),
        "over_constrained": (
            "This joint removes degrees of freedom that earlier joints "
            "already removed; delete it or use a less restrictive type."
        ),
        "conflicting_constraints": (
            "This joint contradicts an earlier joint; the references cannot "
            "all be satisfied at once."
        ),
        "redundant_constraints": (
            "The joint duplicates constraints already imposed by other "
            "joints; the assembly still solves but should be simplified."
        ),
        "malformed_constraints": (
            "The joint references did not produce usable connector "
            "placements; verify the element names on both components."
        ),
        "solver_error": (
            "The native solver failed on this configuration; inspect the "
            "joint references and component placements."
        ),
    }.get(verdict, "Inspect the assembly structure with assembly.list_structure.")


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
