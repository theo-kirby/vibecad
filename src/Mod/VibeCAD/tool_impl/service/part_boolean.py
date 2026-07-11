# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part boolean between standalone shaped objects."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.boolean",
    "description": (
        "Create one native Part boolean (union, cut, or intersection) from exact "
        "named shaped objects. The inputs become children of the result and are "
        "hidden, not deleted; the boolean stays parametric. Do not use this on "
        "features inside a PartDesign Body - use partdesign.boolean there."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["union", "cut", "intersection"],
                "description": (
                    "union fuses all inputs; cut subtracts the tool objects from the "
                    "base object; intersection keeps only shared volume."
                ),
            },
            "base_object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the base object. For cut, material is "
                    "removed from this object."
                ),
            },
            "tool_object_names": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Exact internal names of the other operand objects. For cut, "
                    "these are subtracted from the base."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the boolean result.",
            },
            "refine": {
                "type": "boolean",
                "description": "Remove redundant edges from the result; usually true.",
            },
        },
        "required": [
            "operation",
            "base_object_name",
            "tool_object_names",
            "label",
            "refine",
        ],
        "additionalProperties": False,
    },
}

_NATIVE = {
    "union": ("Part::MultiFuse", "Fusion"),
    "cut": ("Part::Cut", "Cut"),
    "intersection": ("Part::MultiCommon", "Common"),
}


def run(
    service: Any,
    operation: str,
    base_object_name: str,
    tool_object_names: list[str],
    label: str,
    refine: bool,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    native = _NATIVE.get(str(operation or ""))
    if native is None:
        return _invalid("operation must be union, cut, or intersection.")
    base_name = str(base_object_name or "").strip()
    if not base_name:
        return _invalid("base_object_name is required.")
    if not isinstance(tool_object_names, list) or not tool_object_names:
        return _invalid("tool_object_names must contain at least one exact name.")
    tool_names = [str(name or "").strip() for name in tool_object_names]
    if any(not name for name in tool_names):
        return _invalid("tool_object_names cannot contain empty names.")
    if len(set(tool_names)) != len(tool_names):
        return _invalid("tool_object_names cannot contain duplicates.")
    if base_name in tool_names:
        return _invalid("The base object cannot also be a tool object.")
    resolve_error = _resolve_operands(service, [base_name, *tool_names])
    if resolve_error is not None:
        return resolve_error
    type_id, base_object_name_hint = native

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        base = doc.getObject(base_name)
        tools = [doc.getObject(name) for name in tool_names]
        if base is None or any(tool is None for tool in tools):
            raise RuntimeError("A boolean operand no longer exists.")
        boolean = doc.addObject(type_id, base_object_name_hint)
        boolean.Label = clean_label
        if type_id == "Part::Cut":
            if len(tools) == 1:
                boolean.Base = base
                boolean.Tool = tools[0]
            else:
                doc.removeObject(boolean.Name)
                fuse = doc.addObject("Part::MultiFuse", "CutTools")
                fuse.Label = f"{clean_label}_tools"
                fuse.Shapes = tools
                boolean = doc.addObject("Part::Cut", "Cut")
                boolean.Label = clean_label
                boolean.Base = base
                boolean.Tool = fuse
        else:
            boolean.Shapes = [base, *tools]
        if hasattr(boolean, "Refine"):
            boolean.Refine = bool(refine)
        doc.recompute()
        operands = [base, *tools]
        for operand in operands:
            view = getattr(operand, "ViewObject", None)
            if view is not None:
                try:
                    view.Visibility = False
                except Exception:
                    pass
        return {
            "document": doc.Name,
            "feature": boolean.Name,
            "feature_label": boolean.Label,
            "feature_type": boolean.TypeId,
            "operation": operation,
            "base_object": base_name,
            "tool_objects": tool_names,
            "operands_hidden": [operand.Name for operand in operands],
            "shape": domain_runtime.shape_summary(boolean),
            "feature_state": domain_runtime.feature_state_summary(boolean),
        }

    transaction = run_freecad_transaction(
        f"Create Part boolean {operation}: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction, operation=f"boolean_{operation}"
    )


def _resolve_operands(service: Any, names: list[str]) -> dict[str, Any] | None:
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    for name in names:
        obj = doc.getObject(name)
        if obj is None:
            return _invalid(f"Object not found by exact internal name: {name}")
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            return _invalid(f"Object has no shape geometry: {name}")
        if int(len(getattr(shape, "Solids", []) or [])) < 1:
            return _invalid(
                f"Object {name} contains no solid; Part booleans need solid operands.",
                shape=domain_runtime.shape_summary(obj),
            )
    return None


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
