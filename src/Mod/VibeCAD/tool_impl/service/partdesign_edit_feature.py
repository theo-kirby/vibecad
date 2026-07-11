# SPDX-License-Identifier: LGPL-2.1-or-later

"""Surgical in-place editing of an exact native PartDesign feature."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


VECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number", "description": "X component"},
        "y": {"type": "number", "description": "Y component"},
        "z": {"type": "number", "description": "Z component"},
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}

REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "object_name": {
            "type": "string",
            "description": "Exact internal name of the referenced object.",
        },
        "subelements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exact subelement names such as Face3 or Edge4; empty references the whole object.",
        },
    },
    "required": ["object_name", "subelements"],
    "additionalProperties": False,
}

PATCH_SCHEMA = {
    "description": "One property change; kind must match the FreeCAD property type.",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "quantity",
                    "description": "Numeric quantity property such as Length or Angle.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {
                    "type": "number",
                    "description": "New value in the property's native unit.",
                },
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "boolean",
                    "description": "Boolean property such as Reversed or Refine.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {"type": "boolean", "description": "New value."},
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "integer",
                    "description": "Integer property such as Occurrences.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {"type": "integer", "description": "New value."},
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "enumeration",
                    "description": "Enumeration property such as Type or Mode.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {
                    "type": "string",
                    "description": "New value; must be a valid enum entry for the property.",
                },
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "vector",
                    "description": "Vector property such as Direction.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {**VECTOR_SCHEMA, "description": "New vector value."},
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "string",
                    "description": "String property such as Label.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "value": {"type": "string", "description": "New value."},
            },
            "required": ["kind", "property", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "link",
                    "description": "Single-object link property such as Profile.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "object_name": {
                    "type": "string",
                    "description": "Exact internal name of the newly linked object.",
                },
            },
            "required": ["kind", "property", "object_name"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "link_sub",
                    "description": "Object-plus-subelements link property such as UpToFace.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "reference": {**REFERENCE_SCHEMA, "description": "New reference."},
            },
            "required": ["kind", "property", "reference"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "link_list",
                    "description": "Object-list link property such as Originals.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "object_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact internal names of the newly linked objects.",
                },
            },
            "required": ["kind", "property", "object_names"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "link_sub_list",
                    "description": "Reference-list link property such as Base.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
                "references": {
                    "type": "array",
                    "items": REFERENCE_SCHEMA,
                    "description": "New references, in order.",
                },
            },
            "required": ["kind", "property", "references"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "kind": {
                    "const": "clear",
                    "description": "Reset a link property to empty.",
                },
                "property": {
                    "type": "string",
                    "description": "Exact FreeCAD property name.",
                },
            },
            "required": ["kind", "property"],
            "additionalProperties": False,
        },
    ],
}

TOOL_SPEC = {
    "name": "partdesign.edit_feature",
    "description": (
        "Edit writable native properties on one exact existing PartDesign feature in place. "
        "Property kinds are checked against FreeCAD before any mutation; the object is never "
        "replaced. Prefer this over delete-and-recreate for dimension and option changes."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "feature_name": {
                "type": "string",
                "description": "Exact internal name of the feature to edit.",
            },
            "patches": {
                "type": "array",
                "items": PATCH_SCHEMA,
                "minItems": 1,
                "description": "Property changes applied together in order.",
            },
        },
        "required": ["feature_name", "patches"],
        "additionalProperties": False,
    },
}

_PROTECTED_PROPERTIES = {
    "AddSubShape",
    "BaseFeature",
    "ExpressionEngine",
    "Placement",
    "PreviewShape",
    "Shape",
    "ShapeMaterial",
    "SuppressedShape",
    "Visibility",
    "_Body",
    "_ElementMapVersion",
}


def run(
    service: Any,
    feature_name: str,
    patches: list[dict[str, Any]],
) -> dict[str, Any]:
    doc = service._active_document()
    feature = (
        doc.getObject(str(feature_name or "").strip()) if doc is not None else None
    )
    if feature is None:
        return _invalid(f"Feature not found by exact internal name: {feature_name}")
    if not str(getattr(feature, "TypeId", "")).startswith("PartDesign::"):
        return _invalid(f"Object {feature.Name} is not a PartDesign object.")
    if getattr(feature, "TypeId", "") == "PartDesign::Body":
        return _invalid(
            "Use focused Body tools rather than editing Body properties here."
        )
    body = service._partdesign_body_for_feature(feature)
    if body is None:
        return _invalid(f"Feature {feature.Name} is not owned by exactly one Body.")
    if not isinstance(patches, list) or not patches:
        return _invalid("patches must contain at least one typed property change.")
    property_names = [str((patch or {}).get("property") or "") for patch in patches]
    if len(set(property_names)) != len(property_names):
        return _invalid("A property can be changed only once per edit call.")
    validated = []
    for index, patch in enumerate(patches):
        state = _validate_patch(doc, feature, patch)
        if not state.get("ok"):
            state["patch_index"] = index
            state["editable_properties"] = editable_property_summary(feature)
            return state
        validated.append(state)

    state_before = domain_runtime.feature_state_summary(feature)
    shape_before = domain_runtime.shape_summary(feature)
    property_before = {
        state["property"]: _serialize_property(feature, state["property"])
        for state in validated
    }
    base_feature = getattr(feature, "BaseFeature", None)
    base_shape = (
        domain_runtime.shape_summary(base_feature)
        if base_feature is not None
        else {
            "available": True,
            "solids": 0,
            "faces": 0,
            "edges": 0,
            "vertices": 0,
            "volume": 0.0,
        }
    )
    operation = domain_runtime.partdesign_operation_for_feature(feature)
    geometry_affecting = any(
        state["property"] != "Label"
        and not (state["property"] == "Suppressed" and state.get("value") is True)
        for state in validated
    )

    def edit() -> dict[str, Any]:
        import FreeCAD as App

        active_doc = App.ActiveDocument
        if active_doc is None:
            raise RuntimeError("No active document.")
        target = active_doc.getObject(feature.Name)
        target_body = service._get_partdesign_body(body.Name)
        if target is None or target_body is None:
            raise RuntimeError("Feature or owning Body no longer exists.")
        if service._partdesign_body_for_feature(target) != target_body:
            raise RuntimeError("Feature ownership changed before execution.")
        for state in validated:
            _apply_patch(active_doc, target, state)
        active_doc.recompute()
        state_after = domain_runtime.feature_state_summary(target)
        shape_after = domain_runtime.shape_summary(target)
        if operation is not None:
            effect = domain_runtime.partdesign_feature_effect(
                operation,
                base_shape,
                shape_after,
                shape_after,
            )
        else:
            effect = {
                "ok": not state_after.get("marked_invalid")
                and state_after.get("shape_valid") is not False,
                "operation": None,
                "feature_has_shape": not state_after.get("shape_null"),
            }
        valid_after = (
            not state_after.get("marked_invalid")
            and state_after.get("shape_valid") is not False
            and (not geometry_affecting or operation is None or bool(effect.get("ok")))
        )
        return {
            "document": active_doc.Name,
            "body": target_body.Name,
            "feature": target.Name,
            "feature_label": target.Label,
            "feature_type": target.TypeId,
            "same_object": target.Name == feature.Name,
            "properties_before": property_before,
            "properties_after": {
                state["property"]: _serialize_property(target, state["property"])
                for state in validated
            },
            "feature_state_before": state_before,
            "feature_state": state_after,
            "feature_shape_before": shape_before,
            "feature_shape": shape_after,
            "feature_effect": effect,
            "edit_valid": bool(valid_after),
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
            "base_feature": getattr(getattr(target, "BaseFeature", None), "Name", None),
            "editable_properties": editable_property_summary(target),
        }

    transaction = run_freecad_transaction(
        f"Edit PartDesign feature in place: {feature.Name}",
        edit,
    )
    result = (
        transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    )
    ok = bool(transaction.get("ok")) and bool(result.get("edit_valid"))
    response = {
        "ok": ok,
        "operation": "edit_feature",
        "mutation": result,
        "document_delta": transaction.get("document_delta") or {},
        "native_errors": domain_runtime.recompute_errors(transaction),
        "body_state": service._partdesign_body_summary(
            service._get_partdesign_body(body.Name)
        ),
        "failed_feature_retained": not ok,
    }
    if not ok:
        response["error"] = (
            transaction.get("error")
            or (response["native_errors"][-1] if response["native_errors"] else None)
            or f"Feature {feature.Name} remains invalid or ineffective after the edit."
        )
        response["failure"] = {
            "kind": "feature_edit_did_not_recompute_validly",
            "feature": feature.Name,
            "feature_state": result.get("feature_state"),
            "feature_effect": result.get("feature_effect"),
        }
        response["retry_same_call"] = False
    return response


def editable_property_summary(feature: Any) -> list[dict[str, Any]]:
    result = []
    for name in list(getattr(feature, "PropertiesList", []) or []):
        state = _property_contract(feature, name)
        if state.get("ok"):
            result.append(
                {
                    "property": name,
                    "kind": state["kind"],
                    "native_type": state["native_type"],
                    "value": _serialize_property(feature, name),
                    "clearable": state["kind"]
                    in {"link", "link_sub", "link_list", "link_sub_list"},
                    **(
                        {"allowed_values": state["allowed_values"]}
                        if state.get("allowed_values") is not None
                        else {}
                    ),
                }
            )
    return result


def _validate_patch(doc: Any, feature: Any, patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return _invalid("Each patch must be an object.")
    name = str(patch.get("property") or "").strip()
    contract = _property_contract(feature, name)
    if not contract.get("ok"):
        return contract
    kind = str(patch.get("kind") or "")
    if kind == "clear":
        if contract["kind"] not in {"link", "link_sub", "link_list", "link_sub_list"}:
            return _invalid(
                f"Property {name} cannot be cleared because its native kind is {contract['kind']}.",
                property=name,
                native_type=contract["native_type"],
            )
        return {
            **contract,
            "property": name,
            "kind": "clear",
            "native_kind": contract["kind"],
            "value": [] if contract["kind"] in {"link_list", "link_sub_list"} else None,
        }
    if kind != contract["kind"]:
        return _invalid(
            f"Property {name} requires patch kind {contract['kind']}, not {kind}.",
            property=name,
            native_type=contract["native_type"],
        )
    result = {**contract, "property": name}
    if kind == "quantity":
        try:
            result["value"] = float(patch["value"])
        except (KeyError, TypeError, ValueError):
            return _invalid(f"Property {name} requires a numeric value.")
    elif kind == "boolean":
        if not isinstance(patch.get("value"), bool):
            return _invalid(f"Property {name} requires a boolean value.")
        result["value"] = patch["value"]
    elif kind == "integer":
        value = patch.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            return _invalid(f"Property {name} requires an integer value.")
        result["value"] = value
    elif kind == "enumeration":
        value = str(patch.get("value") or "")
        if value not in contract["allowed_values"]:
            return _invalid(
                f"Property {name} enumeration value is invalid: {value}",
                allowed_values=contract["allowed_values"],
            )
        result["value"] = value
    elif kind == "vector":
        try:
            result["value"] = tuple(
                float(patch["value"][key]) for key in ("x", "y", "z")
            )
        except (KeyError, TypeError, ValueError):
            return _invalid(f"Property {name} requires numeric x, y, and z.")
    elif kind == "string":
        result["value"] = str(patch.get("value") or "")
    elif kind == "link":
        linked = _exact_object(doc, patch.get("object_name"), feature)
        if not linked.get("ok"):
            return linked
        result["value"] = linked["object"]
    elif kind == "link_sub":
        reference = _reference(doc, patch.get("reference"), feature)
        if not reference.get("ok"):
            return reference
        result["value"] = reference["value"]
    elif kind == "link_list":
        names = patch.get("object_names")
        if not isinstance(names, list):
            return _invalid(f"Property {name} requires object_names as an array.")
        values = []
        for object_name in names:
            linked = _exact_object(doc, object_name, feature)
            if not linked.get("ok"):
                return linked
            values.append(linked["object"])
        result["value"] = values
    elif kind == "link_sub_list":
        references = patch.get("references")
        if not isinstance(references, list):
            return _invalid(f"Property {name} requires references as an array.")
        values = []
        for reference_value in references:
            reference = _reference(doc, reference_value, feature)
            if not reference.get("ok"):
                return reference
            values.append(reference["value"])
        result["value"] = values
    return result


def _property_contract(feature: Any, name: str) -> dict[str, Any]:
    if not name or name not in list(getattr(feature, "PropertiesList", []) or []):
        return _invalid(f"Feature {feature.Name} has no property named {name}.")
    if name in _PROTECTED_PROPERTIES or name.startswith("_"):
        return _invalid(
            f"Property {name} is owned by FreeCAD and cannot be edited directly."
        )
    editor_mode = [str(value) for value in list(feature.getEditorMode(name) or [])]
    status = [str(value) for value in list(feature.getPropertyStatus(name) or [])]
    blocked = {"ReadOnly", "Output", "NoModify"}
    if blocked.intersection(editor_mode) or blocked.intersection(status):
        return _invalid(
            f"Property {name} is currently read-only. Change its controlling mode first.",
            editor_mode=editor_mode,
            property_status=status,
        )
    native_type = str(feature.getTypeIdOfProperty(name) or "")
    kind = _patch_kind(native_type)
    if kind is None:
        return _invalid(
            f"Property {name} has unsupported native type {native_type}.",
            native_type=native_type,
        )
    result = {"ok": True, "native_type": native_type, "kind": kind}
    if kind == "enumeration":
        result["allowed_values"] = [
            str(value) for value in list(feature.getEnumerationsOfProperty(name) or [])
        ]
    return result


def _patch_kind(native_type: str) -> str | None:
    if native_type == "App::PropertyBool":
        return "boolean"
    if native_type.startswith("App::PropertyInteger"):
        return "integer"
    if native_type == "App::PropertyEnumeration":
        return "enumeration"
    if native_type == "App::PropertyVector":
        return "vector"
    if native_type == "App::PropertyString":
        return "string"
    if native_type in {"App::PropertyLink", "App::PropertyLinkHidden"}:
        return "link"
    if native_type == "App::PropertyLinkSub":
        return "link_sub"
    if native_type == "App::PropertyLinkList":
        return "link_list"
    if native_type in {"App::PropertyLinkSubList", "App::PropertyXLinkSubList"}:
        return "link_sub_list"
    if native_type.startswith("App::Property") and any(
        token in native_type
        for token in ("Length", "Distance", "Angle", "Float", "Quantity")
    ):
        return "quantity"
    return None


def _exact_object(doc: Any, name: Any, feature: Any) -> dict[str, Any]:
    clean = str(name or "").strip()
    obj = doc.getObject(clean) if clean else None
    if obj is None:
        return _invalid(f"Linked object not found by exact internal name: {clean}")
    if obj == feature:
        return _invalid(f"Feature {feature.Name} cannot link to itself.")
    return {"ok": True, "object": obj}


def _reference(doc: Any, value: Any, feature: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _invalid("A link_sub reference must be an object.")
    linked = _exact_object(doc, value.get("object_name"), feature)
    if not linked.get("ok"):
        return linked
    subelements = value.get("subelements")
    if not isinstance(subelements, list):
        return _invalid("reference.subelements must be an array.")
    return {
        "ok": True,
        "value": (linked["object"], [str(item) for item in subelements]),
    }


def _apply_patch(doc: Any, feature: Any, state: dict[str, Any]) -> None:
    value = state["value"]
    if state["kind"] == "vector":
        import FreeCAD as App

        value = App.Vector(*value)
    setattr(feature, state["property"], value)


def _serialize_property(feature: Any, name: str) -> Any:
    value = getattr(feature, name)
    native_type = str(feature.getTypeIdOfProperty(name) or "")
    kind = _patch_kind(native_type)
    if kind == "vector":
        return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}
    if kind in {"quantity", "integer"}:
        return float(value) if kind == "quantity" else int(value)
    if kind in {"boolean", "string", "enumeration"}:
        return bool(value) if kind == "boolean" else str(value)
    if kind == "link":
        return getattr(value, "Name", None)
    if kind == "link_sub":
        if not value:
            return None
        obj, subelements = value
        return {
            "object_name": getattr(obj, "Name", None),
            "subelements": [str(item) for item in list(subelements or [])],
        }
    if kind == "link_list":
        return [getattr(item, "Name", None) for item in list(value or [])]
    if kind == "link_sub_list":
        result = []
        for obj, subelements in list(value or []):
            result.append(
                {
                    "object_name": getattr(obj, "Name", None),
                    "subelements": [str(item) for item in list(subelements or [])],
                }
            )
        return result
    return str(value)


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
