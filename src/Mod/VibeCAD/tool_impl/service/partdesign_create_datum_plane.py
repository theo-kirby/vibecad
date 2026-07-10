# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create a native PartDesign datum plane on an explicit Body origin plane."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_VECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "z": {"type": "number"},
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}

TOOL_SPEC = {
    "name": "partdesign.create_datum_plane",
    "description": (
        "Create one native PartDesign datum plane in an exact Body, attached to an exact Body "
        "origin plane with an explicit local translation and axis-angle rotation. Use for "
        "offset sections, angled features, loft stations, and controlled construction references."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "body_name": {"type": "string"},
            "label": {"type": "string"},
            "support_plane": {
                "type": "string",
                "enum": ["XY_Plane", "XZ_Plane", "YZ_Plane"],
            },
            "offset": _VECTOR_SCHEMA,
            "rotation_axis": _VECTOR_SCHEMA,
            "rotation_degrees": {"type": "number"},
        },
        "required": [
            "body_name",
            "label",
            "support_plane",
            "offset",
            "rotation_axis",
            "rotation_degrees",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    body_name: str,
    label: str,
    support_plane: str,
    offset: dict[str, float],
    rotation_axis: dict[str, float],
    rotation_degrees: float,
) -> dict[str, Any]:
    body = service._get_partdesign_body(body_name)
    if body is None:
        return _invalid(f"PartDesign Body not found: {body_name}")
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    support = service._partdesign_origin_feature(body, str(support_plane or ""))
    if support is None:
        return _invalid(f"Body origin plane not found: {support_plane}")
    parsed_offset = _vector(offset, "offset", allow_zero=True)
    if not parsed_offset.get("ok"):
        return parsed_offset
    parsed_axis = _vector(rotation_axis, "rotation_axis", allow_zero=False)
    if not parsed_axis.get("ok"):
        return parsed_axis
    tip_block = domain_runtime.invalid_partdesign_tip(body)
    if tip_block is not None:
        return _invalid(
            "The target Body has an invalid or zero-effect Tip.",
            tip_state=tip_block,
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_body = service._get_partdesign_body(body.Name)
        target_support = doc.getObject(support.Name)
        if target_body is None or target_support is None:
            raise RuntimeError("Datum plane Body or support no longer exists.")
        datum = target_body.newObject("PartDesign::Plane", "DatumPlane")
        datum.Label = clean_label
        datum.AttachmentSupport = [(target_support, "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(
            App.Vector(*parsed_offset["vector"]),
            App.Rotation(App.Vector(*parsed_axis["vector"]), float(rotation_degrees)),
        )
        doc.recompute()
        return {
            "document": doc.Name,
            "body": target_body.Name,
            "datum": datum.Name,
            "datum_label": datum.Label,
            "datum_type": datum.TypeId,
            "support": target_support.Name,
            "map_mode": str(datum.MapMode),
            "attachment_offset": service._placement_summary(datum.AttachmentOffset),
            "state": [str(value) for value in list(datum.State)],
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
        }

    return _response(
        service,
        body,
        run_freecad_transaction(f"Create datum plane: {clean_label}", create),
    )


def _vector(value: Any, name: str, *, allow_zero: bool) -> dict[str, Any]:
    try:
        vector = (float(value["x"]), float(value["y"]), float(value["z"]))
    except (KeyError, TypeError, ValueError):
        return _invalid(f"{name} requires numeric x, y, and z.")
    if not allow_zero and sum(component * component for component in vector) <= 1e-18:
        return _invalid(f"{name} must be non-zero.")
    return {"ok": True, "vector": vector}


def _response(service: Any, body: Any, transaction: dict[str, Any]) -> dict[str, Any]:
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "mutation": result,
        "document_delta": transaction.get("document_delta") or {},
        "native_errors": domain_runtime.recompute_errors(transaction),
        "body_state": service._partdesign_body_summary(body),
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "Datum plane creation failed."
        response["retry_same_call"] = False
    return response


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
