# SPDX-License-Identifier: LGPL-2.1-or-later

"""Add one native FEM constraint (support or load) to an exact analysis."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_REFERENCE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "object_name": {
            "type": "string",
            "description": (
                "Exact internal name of the shaped model object the "
                "constraint acts on (the object being analyzed, not the "
                "FEM mesh)."
            ),
        },
        "element": {
            "type": "string",
            "description": (
                "Exact subelement to constrain, e.g. 'Face1', 'Edge3', or "
                "'Vertex2' from part.find_subelements."
            ),
        },
    },
    "required": ["object_name", "element"],
    "additionalProperties": False,
}


TOOL_SPEC = {
    "name": "fem.add_constraint",
    "description": (
        "Add one native FEM constraint to an exact analysis on exact model "
        "subelements. A static analysis needs at least one fixed support "
        "and one load (force, pressure, or gravity) or it cannot solve. "
        "Constraints reference the model object's faces/edges/vertices, not "
        "the FEM mesh."
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
            "label": {
                "type": "string",
                "description": "Visible label for the new constraint object.",
            },
            "constraint": {
                "description": "Constraint behavior; choose exactly one variant.",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "fixed",
                                "description": (
                                    "Fixed support: the referenced elements "
                                    "cannot move in any direction. Every "
                                    "static analysis needs at least one."
                                ),
                            },
                            "references": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _REFERENCE_ITEM_SCHEMA,
                                "description": (
                                    "Model subelements to hold fixed, "
                                    "typically mounting faces."
                                ),
                            },
                        },
                        "required": ["type", "references"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "force",
                                "description": (
                                    "Force load: a total force in newtons "
                                    "distributed evenly over the referenced "
                                    "elements, acting along the face normal "
                                    "unless a direction edge is given."
                                ),
                            },
                            "references": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _REFERENCE_ITEM_SCHEMA,
                                "description": ("Model subelements the force acts on."),
                            },
                            "force_n": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Total force magnitude in newtons, "
                                    "distributed over all references."
                                ),
                            },
                            "direction": {
                                **_REFERENCE_ITEM_SCHEMA,
                                "description": (
                                    "Optional straight edge or planar face "
                                    "whose direction the force follows; omit "
                                    "to act along each referenced face's "
                                    "normal."
                                ),
                                "required": ["object_name", "element"],
                            },
                            "reversed": {
                                "type": "boolean",
                                "description": (
                                    "true flips the force to act opposite "
                                    "the direction edge or face normal."
                                ),
                            },
                        },
                        "required": ["type", "references", "force_n", "reversed"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "pressure",
                                "description": (
                                    "Pressure load in MPa acting normal to "
                                    "the referenced faces, e.g. hydraulic or "
                                    "contact pressure."
                                ),
                            },
                            "references": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _REFERENCE_ITEM_SCHEMA,
                                "description": "Faces the pressure acts on.",
                            },
                            "pressure_mpa": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": ("Pressure magnitude in MPa (N/mm^2)."),
                            },
                            "reversed": {
                                "type": "boolean",
                                "description": (
                                    "false pushes into the face (compression), "
                                    "true pulls away from it (suction)."
                                ),
                            },
                        },
                        "required": ["type", "references", "pressure_mpa", "reversed"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "gravity",
                                "description": (
                                    "Self-weight load: standard gravity "
                                    "(9.81 m/s^2, global -Z) applied to the "
                                    "whole model; needs no references but "
                                    "does need a material with density."
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
                                "const": "temperature",
                                "description": (
                                    "Fixed temperature in kelvin on the "
                                    "referenced elements, for thermomech "
                                    "analyses."
                                ),
                            },
                            "references": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _REFERENCE_ITEM_SCHEMA,
                                "description": (
                                    "Model subelements held at the temperature."
                                ),
                            },
                            "temperature_k": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Temperature in kelvin (293.15 K = 20 C)."
                                ),
                            },
                        },
                        "required": ["type", "references", "temperature_k"],
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "required": ["analysis_name", "label", "constraint"],
        "additionalProperties": False,
    },
}


_ELEMENT_PREFIXES = ("Face", "Edge", "Vertex")


def _validate_references(
    service: Any,
    raw_refs: Any,
) -> tuple[list[tuple[str, str]], str | None]:
    doc = service._active_document()
    if doc is None:
        return [], "No active document."
    if not isinstance(raw_refs, list) or not raw_refs:
        return [], "references must contain at least one item."
    refs: list[tuple[str, str]] = []
    for entry in raw_refs:
        if not isinstance(entry, dict):
            return [], "Each references item must be an object."
        object_name = str(entry.get("object_name") or "").strip()
        element = str(entry.get("element") or "").strip()
        obj = doc.getObject(object_name) if object_name else None
        if obj is None:
            return [], f"Object not found by exact internal name: {object_name}"
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            return [], f"Object has no shape geometry: {object_name}"
        if not element.startswith(_ELEMENT_PREFIXES):
            return [], (
                f"Element names must look like Face1, Edge3, or Vertex2; got: {element}"
            )
        try:
            shape.getElement(element)
        except Exception:
            return [], (
                f"{object_name} has no subelement named {element}. Use "
                "part.find_subelements to list exact names."
            )
        refs.append((object_name, element))
    if len(set(refs)) != len(refs):
        return [], "references cannot contain duplicate items."
    return refs, None


def run(
    service: Any,
    analysis_name: str,
    label: str,
    constraint: dict[str, Any],
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    analysis = service._get_fem_analysis(str(analysis_name or "").strip())
    if analysis is None:
        return _invalid(
            f"FEM analysis not found by exact internal name: {analysis_name}. "
            "Call fem.list_analysis for exact names."
        )
    if not isinstance(constraint, dict):
        return _invalid("constraint must be an object with a 'type' field.")
    constraint_type = str(constraint.get("type") or "").strip()
    if constraint_type not in ("fixed", "force", "pressure", "gravity", "temperature"):
        return _invalid(
            f"Unknown constraint type: {constraint_type}. Choose one of: "
            "fixed, force, pressure, gravity, temperature."
        )
    try:
        import ObjectsFem  # noqa: F401
    except ImportError:
        return _invalid(
            "The FEM workbench is not available in this FreeCAD build; "
            "constraints cannot be added."
        )

    refs: list[tuple[str, str]] = []
    if constraint_type != "gravity":
        refs, error = _validate_references(service, constraint.get("references"))
        if error is not None:
            return _invalid(error)
    direction_ref: tuple[str, str] | None = None
    if constraint_type == "force" and constraint.get("direction") is not None:
        direction_refs, error = _validate_references(service, [constraint["direction"]])
        if error is not None:
            return _invalid(f"direction: {error}")
        direction_ref = direction_refs[0]

    def create() -> dict[str, Any]:
        import FreeCAD as App
        import ObjectsFem

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(analysis.Name)
        if target is None:
            raise RuntimeError("The analysis no longer exists.")
        references = [
            (active.getObject(object_name), element) for object_name, element in refs
        ]
        if constraint_type == "fixed":
            con = ObjectsFem.makeConstraintFixed(active, "Fixed")
            con.References = references
        elif constraint_type == "force":
            con = ObjectsFem.makeConstraintForce(active, "Force")
            con.References = references
            con.Force = f"{float(constraint['force_n'])} N"
            if direction_ref is not None:
                direction_obj = active.getObject(direction_ref[0])
                con.Direction = (direction_obj, [direction_ref[1]])
            con.Reversed = bool(constraint.get("reversed"))
        elif constraint_type == "pressure":
            con = ObjectsFem.makeConstraintPressure(active, "Pressure")
            con.References = references
            con.Pressure = f"{float(constraint['pressure_mpa'])} MPa"
            con.Reversed = bool(constraint.get("reversed"))
        elif constraint_type == "gravity":
            con = ObjectsFem.makeConstraintSelfWeight(active, "Gravity")
        else:
            con = ObjectsFem.makeConstraintTemperature(active, "Temperature")
            con.References = references
            con.Temperature = f"{float(constraint['temperature_k'])} K"
        con.Label = clean_label
        target.addObject(con)
        active.recompute()
        return {
            "document": active.Name,
            "analysis": target.Name,
            "constraint_object": con.Name,
            "constraint_object_label": con.Label,
            "constraint_type": constraint_type,
            "references": [
                {"object_name": object_name, "element": element}
                for object_name, element in refs
            ],
        }

    transaction = run_freecad_transaction(
        f"Add FEM constraint: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "add_constraint"},
        next_action=(
            "Add remaining supports/loads, then generate the mesh with "
            "fem.mesh_analysis and run fem.solve."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
