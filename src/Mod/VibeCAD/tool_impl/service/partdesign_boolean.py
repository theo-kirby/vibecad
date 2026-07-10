# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Boolean tool."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "partdesign.boolean",
    "description": (
        "Create one native PartDesign Boolean in an exact target Body using exact tool Bodies. "
        "The result reports the intentional native ownership move of every consumed tool Body."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "target_body_name": {"type": "string"},
            "tool_body_names": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "operation": {"type": "string", "enum": ["fuse", "cut", "common"]},
            "label": {"type": "string"},
            "refine": {"type": "boolean"},
            "fuzzy_tolerance": {"type": "number", "minimum": 0},
        },
        "required": [
            "target_body_name", "tool_body_names", "operation", "label", "refine",
            "fuzzy_tolerance",
        ],
        "additionalProperties": False,
    },
}

_NATIVE_OPERATION = {"fuse": "Fuse", "cut": "Cut", "common": "Common"}


def run(
    service: Any,
    target_body_name: str,
    tool_body_names: list[str],
    operation: str,
    label: str,
    refine: bool,
    fuzzy_tolerance: float,
) -> dict[str, Any]:
    target = service._get_partdesign_body(str(target_body_name or "").strip())
    if target is None:
        return _invalid(
            f"Target Body not found by exact internal name: {target_body_name}"
        )
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    requested_operation = str(operation or "")
    native_operation = _NATIVE_OPERATION.get(requested_operation)
    if native_operation is None:
        return _invalid("operation must be fuse, cut, or common.")
    try:
        tolerance = float(fuzzy_tolerance)
    except (TypeError, ValueError):
        return _invalid("fuzzy_tolerance must be numeric and non-negative.")
    if tolerance < 0:
        return _invalid("fuzzy_tolerance must be non-negative.")
    if not isinstance(tool_body_names, list) or not tool_body_names:
        return _invalid("tool_body_names must contain at least one exact Body name.")
    names = [str(name or "").strip() for name in tool_body_names]
    if any(not name for name in names):
        return _invalid("tool_body_names cannot contain empty names.")
    if len(set(names)) != len(names):
        return _invalid("tool_body_names cannot contain duplicates.")
    if target.Name in names:
        return _invalid("The target Body cannot also be a tool Body.")
    target_state = _valid_body_state(service, target, role="target")
    if not target_state.get("ok"):
        return target_state
    tools = []
    tools_before = []
    for name in names:
        body = service._get_partdesign_body(name)
        if body is None:
            return _invalid(f"Tool Body not found by exact internal name: {name}")
        state = _valid_body_state(service, body, role="tool")
        if not state.get("ok"):
            return state
        parent = body.getParentGeoFeatureGroup()
        tools.append(body)
        tools_before.append(
            {
                "body": body.Name,
                "tip": getattr(getattr(body, "Tip", None), "Name", None),
                "shape": domain_runtime.shape_summary(body),
                "parent": getattr(parent, "Name", None),
                "parent_type": getattr(parent, "TypeId", None),
            }
        )
    body_shape_before = domain_runtime.shape_summary(target)

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_body = service._get_partdesign_body(target.Name)
        target_tools = [service._get_partdesign_body(name) for name in names]
        if target_body is None or any(body is None for body in target_tools):
            raise RuntimeError("Boolean target or tool Body no longer exists.")
        if getattr(getattr(target_body, "Tip", None), "Name", None) != target_state["tip"]:
            raise RuntimeError("Boolean target Tip changed before execution.")
        boolean = target_body.newObject("PartDesign::Boolean", "Boolean")
        boolean.Label = clean_label
        added = list(boolean.setObjects(target_tools))
        boolean.Type = native_operation
        boolean.Refine = bool(refine)
        boolean.FuzzyTolerance = tolerance
        target_body.Tip = boolean
        doc.recompute()
        grouped_names = [body.Name for body in list(boolean.Group)]
        if grouped_names != names or [body.Name for body in added] != names:
            raise RuntimeError(
                "FreeCAD did not accept the exact ordered Boolean tool Body list. "
                f"Requested {names}, grouped {grouped_names}, added {[body.Name for body in added]}."
            )
        effect = domain_runtime.finalize_partdesign_feature_effect(
            doc,
            target_body,
            boolean,
            f"boolean_{requested_operation}",
            body_shape_before,
        )
        tools_after = []
        for tool_body in target_tools:
            parent = tool_body.getParentGeoFeatureGroup()
            tools_after.append(
                {
                    "body": tool_body.Name,
                    "parent": getattr(parent, "Name", None),
                    "parent_type": getattr(parent, "TypeId", None),
                    "consumed_by_boolean": tool_body in list(boolean.Group),
                }
            )
        return {
            "document": doc.Name,
            "body": target_body.Name,
            "feature": boolean.Name,
            "feature_label": boolean.Label,
            "feature_type": boolean.TypeId,
            "operation": requested_operation,
            "native_operation": str(boolean.Type),
            "tool_bodies": names,
            "tools_before": tools_before,
            "tools_after": tools_after,
            "refine": bool(boolean.Refine),
            "fuzzy_tolerance": float(boolean.FuzzyTolerance),
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
            "base_feature": getattr(getattr(boolean, "BaseFeature", None), "Name", None),
            **effect,
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign Boolean {requested_operation}: {clean_label}",
        create,
    )
    return domain_runtime.partdesign_feature_response(
        service,
        transaction,
        operation=f"boolean_{requested_operation}",
    )


def _valid_body_state(service: Any, body: Any, *, role: str) -> dict[str, Any]:
    tip = getattr(body, "Tip", None)
    if tip is None:
        return _invalid(f"Boolean {role} Body {body.Name} has no Tip feature.")
    tip_state = domain_runtime.invalid_partdesign_tip(body)
    shape = domain_runtime.shape_summary(body)
    if tip_state is not None:
        return _invalid(
            f"Boolean {role} Body {body.Name} has an invalid or zero-effect Tip.",
            tip_state=tip_state,
        )
    if int(shape.get("solids", 0) or 0) != 1:
        return _invalid(
            f"Boolean {role} Body {body.Name} must contain exactly one solid.",
            body_shape=shape,
        )
    return {"ok": True, "tip": tip.Name, "shape": shape}


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
