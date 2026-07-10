# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Sketcher sketch owned by an explicit PartDesign Body."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime, partdesign_find_subelements


_ORIGIN_PLANES = ("XY_Plane", "XZ_Plane", "YZ_Plane")

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
    "name": "partdesign.create_sketch",
    "description": (
        "Create one native Sketcher sketch inside an explicitly named PartDesign "
        "Body. Attach it to a Body origin plane, a datum plane in that Body, or one exact "
        "planar face. A face query is accepted only when it resolves uniquely; ambiguous "
        "queries return candidates and create nothing."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "body_name": {
                "type": "string",
                "description": "Exact internal PartDesign Body name from current CAD state.",
            },
            "label": {"type": "string"},
            "support_type": {
                "type": "string",
                "enum": ["origin_plane", "datum_plane", "planar_face"],
            },
            "plane": {"type": "string", "enum": list(_ORIGIN_PLANES)},
            "support_object": {
                "type": "string",
                "description": "Exact internal datum-plane or feature name.",
            },
            "subelement": {
                "type": "string",
                "description": "Exact planar face name such as Face3.",
            },
            "normal": _VECTOR_SCHEMA,
            "near_point": _VECTOR_SCHEMA,
            "normal_tolerance_degrees": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 180,
            },
        },
        "required": ["body_name", "label", "support_type"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    body_name: str,
    label: str,
    support_type: str,
    plane: str | None = None,
    support_object: str | None = None,
    subelement: str | None = None,
    normal: dict[str, float] | None = None,
    near_point: dict[str, float] | None = None,
    normal_tolerance_degrees: float = 5.0,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    clean_support_type = str(support_type or "").strip()
    if clean_support_type not in {"origin_plane", "datum_plane", "planar_face"}:
        return _invalid(
            "support_type must be origin_plane, datum_plane, or planar_face."
        )
    body = service._get_partdesign_body(body_name)
    if body is None:
        return _invalid(
            f"PartDesign Body not found by exact internal name: {body_name}",
            requested_body=body_name,
        )
    body_block = domain_runtime.invalid_partdesign_tip(body)
    if body_block is not None:
        return {
            "ok": False,
            "error": "The target Body has an invalid Tip; repair or delete that feature before adding a sketch.",
            "body": body.Name,
            "tip_state": body_block,
            "retry_same_call": False,
        }

    support_resolution = _resolve_support(
        service,
        body,
        clean_support_type,
        plane=plane,
        support_object=support_object,
        subelement=subelement,
        normal=normal,
        near_point=near_point,
        normal_tolerance_degrees=normal_tolerance_degrees,
    )
    if not support_resolution.get("ok"):
        return support_resolution
    support = support_resolution["object"]
    support_subelement = str(support_resolution.get("subelement") or "")

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document. Create or open a document in FreeCAD first.")
        target_body = service._get_partdesign_body(body.Name)
        if target_body is None:
            raise RuntimeError(f"PartDesign Body no longer exists: {body.Name}")
        target_support = doc.getObject(support.Name)
        if target_support is None:
            raise RuntimeError(f"Sketch support no longer exists: {support.Name}")

        sketch = target_body.newObject("Sketcher::SketchObject", "Sketch")
        sketch.Label = clean_label
        sketch.AttachmentSupport = (target_support, [support_subelement])
        sketch.MapMode = "FlatFace"
        doc.recompute()
        return {
            "document": doc.Name,
            "body": target_body.Name,
            "sketch": sketch.Name,
            "sketch_label": sketch.Label,
            "support_type": clean_support_type,
            "support_object": target_support.Name,
            "subelement": support_subelement,
            "map_mode": str(sketch.MapMode),
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign sketch: {clean_label}",
        create,
    )
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "mutation": result,
        "document_delta": transaction.get("document_delta") or {},
        "recompute_errors": domain_runtime.recompute_errors(transaction),
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "PartDesign sketch creation failed."
    return response


def _resolve_support(
    service: Any,
    body: Any,
    support_type: str,
    *,
    plane: str | None,
    support_object: str | None,
    subelement: str | None,
    normal: dict[str, float] | None,
    near_point: dict[str, float] | None,
    normal_tolerance_degrees: float,
) -> dict[str, Any]:
    if support_type == "origin_plane":
        requested_plane = str(plane or "").strip()
        if requested_plane not in _ORIGIN_PLANES:
            return _invalid(
                "plane is required for origin_plane support and must be XY_Plane, XZ_Plane, or YZ_Plane."
            )
        origin_plane = service._partdesign_origin_feature(body, requested_plane)
        if origin_plane is None:
            return _invalid(f"Body origin plane not found: {requested_plane}")
        return {
            "ok": True,
            "object": origin_plane,
            "subelement": "",
            "resolution": "exact_origin_plane",
        }

    object_name = str(support_object or "").strip()
    if not object_name:
        return _invalid(f"support_object is required for {support_type} support.")
    doc = service._active_document()
    target = doc.getObject(object_name) if doc is not None else None
    if target is None:
        return _invalid(f"Support object not found by exact internal name: {object_name}")
    owner = service._partdesign_body_for_feature(target)
    if owner is not body:
        return _invalid(
            f"Support object {target.Name} is not owned by Body {body.Name}.",
            support_owner=getattr(owner, "Name", None),
            target_body=body.Name,
        )

    if support_type == "datum_plane":
        if getattr(target, "TypeId", "") != "PartDesign::Plane":
            return _invalid(
                f"Support object {target.Name} is {target.TypeId}, not PartDesign::Plane."
            )
        return {
            "ok": True,
            "object": target,
            "subelement": "",
            "resolution": "exact_datum_plane",
        }

    requested_face = str(subelement or "").strip()
    if not requested_face and normal is None and near_point is None:
        return _invalid(
            "planar_face support requires subelement or a normal/near_point query."
        )
    query = partdesign_find_subelements.run(
        service,
        object_name=target.Name,
        element_type="face",
        geometry_type="plane",
        normal=normal,
        normal_tolerance_degrees=float(normal_tolerance_degrees),
        near_point=near_point,
    )
    if not query.get("ok"):
        return {
            "ok": False,
            "error": query.get("error") or "Planar-face query failed.",
            "face_query": query,
            "retry_same_call": False,
        }
    matches = [item for item in query.get("matches", []) if isinstance(item, dict)]
    if requested_face:
        selected = next((item for item in matches if item.get("name") == requested_face), None)
        if selected is None:
            return {
                "ok": False,
                "error": f"{requested_face} is not a matching planar face on {target.Name}.",
                "candidates": matches,
                "retry_same_call": False,
            }
    elif len(matches) == 1:
        selected = matches[0]
    elif not matches:
        return {
            "ok": False,
            "error": f"No planar face on {target.Name} matches the supplied query.",
            "candidates": [],
            "retry_same_call": False,
        }
    else:
        return {
            "ok": False,
            "error": (
                f"Planar-face query is ambiguous on {target.Name}; provide one candidate's "
                "exact subelement name."
            ),
            "candidates": matches,
            "retry_same_call": False,
        }
    return {
        "ok": True,
        "object": target,
        "subelement": str(selected["name"]),
        "resolution": "exact_face" if requested_face else "unique_face_query",
        "selected": selected,
    }


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "retry_same_call": False,
        **details,
    }
