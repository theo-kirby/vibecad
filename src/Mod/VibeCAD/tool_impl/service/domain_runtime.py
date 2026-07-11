# SPDX-License-Identifier: LGPL-2.1-or-later

"""Workbench/domain read-tool implementations outside ``VibeCADCore``."""

from __future__ import annotations

import math
from typing import Any


def bound_box_summary(bound_box: Any) -> dict[str, Any] | None:
    if bound_box is None:
        return None
    try:
        return {
            "xmin": float(bound_box.XMin),
            "ymin": float(bound_box.YMin),
            "zmin": float(bound_box.ZMin),
            "xmax": float(bound_box.XMax),
            "ymax": float(bound_box.YMax),
            "zmax": float(bound_box.ZMax),
            "xlength": float(bound_box.XLength),
            "ylength": float(bound_box.YLength),
            "zlength": float(bound_box.ZLength),
        }
    except Exception:
        return None


def shape_summary(obj: Any) -> dict[str, Any]:
    try:
        shape = getattr(obj, "Shape", None)
    except Exception:
        shape = None
    if shape is None:
        return {
            "available": False,
            "solids": 0,
            "faces": 0,
            "edges": 0,
            "vertices": 0,
            "volume": 0.0,
        }
    try:
        summary = {
            "available": True,
            "solids": len(getattr(shape, "Solids", []) or []),
            "faces": len(getattr(shape, "Faces", []) or []),
            "edges": len(getattr(shape, "Edges", []) or []),
            "vertices": len(getattr(shape, "Vertexes", []) or []),
            "volume": float(getattr(shape, "Volume", 0.0) or 0.0),
        }
    except Exception as exc:
        return {
            "available": False,
            "solids": 0,
            "faces": 0,
            "edges": 0,
            "vertices": 0,
            "volume": 0.0,
            "error": str(exc),
        }
    try:
        bound_box = bound_box_summary(getattr(shape, "BoundBox", None))
    except Exception:
        bound_box = None
    if bound_box:
        summary["bound_box"] = bound_box
    return summary


def shape_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta = {
        "volume_delta": float(after.get("volume", 0.0) or 0.0)
        - float(before.get("volume", 0.0) or 0.0),
        "solids_delta": int(after.get("solids", 0) or 0)
        - int(before.get("solids", 0) or 0),
        "faces_delta": int(after.get("faces", 0) or 0)
        - int(before.get("faces", 0) or 0),
        "edges_delta": int(after.get("edges", 0) or 0)
        - int(before.get("edges", 0) or 0),
        "vertices_delta": int(after.get("vertices", 0) or 0)
        - int(before.get("vertices", 0) or 0),
    }
    before_box = (
        before.get("bound_box") if isinstance(before.get("bound_box"), dict) else {}
    )
    after_box = (
        after.get("bound_box") if isinstance(after.get("bound_box"), dict) else {}
    )
    box_delta = {}
    for key in (
        "xmin",
        "ymin",
        "zmin",
        "xmax",
        "ymax",
        "zmax",
        "xlength",
        "ylength",
        "zlength",
    ):
        if key in before_box and key in after_box:
            box_delta[f"{key}_delta"] = float(after_box.get(key, 0.0) or 0.0) - float(
                before_box.get(key, 0.0) or 0.0
            )
    if box_delta:
        delta["bound_box_delta"] = box_delta
    return delta


def partdesign_feature_effect(
    operation: str,
    body_shape_before: dict[str, Any],
    body_shape_after: dict[str, Any],
    feature_shape: dict[str, Any],
) -> dict[str, Any]:
    delta = shape_delta(body_shape_before, body_shape_after)
    feature_has_shape = bool(feature_shape.get("available")) and (
        int(feature_shape.get("solids", 0) or 0) > 0
        or int(feature_shape.get("faces", 0) or 0) > 0
        or abs(float(feature_shape.get("volume", 0.0) or 0.0)) > 1e-9
    )
    volume_delta = float(delta.get("volume_delta", 0.0) or 0.0)
    topology_changed = any(
        int(delta.get(key, 0) or 0) != 0
        for key in ("solids_delta", "faces_delta", "edges_delta", "vertices_delta")
    )
    bound_box_changed = any(
        abs(float(value or 0.0)) > 1e-9
        for value in (delta.get("bound_box_delta") or {}).values()
    )
    if operation in {
        "pad",
        "revolution",
        "additive_loft",
        "additive_pipe",
        "additive_helix",
        "additive_primitive",
    }:
        expected_direction = volume_delta > 1e-9
        effect_ok = feature_has_shape and expected_direction
    elif operation in {
        "pocket",
        "hole",
        "groove",
        "subtractive_loft",
        "subtractive_pipe",
        "subtractive_helix",
        "subtractive_primitive",
        "boolean_cut",
        "boolean_common",
    }:
        expected_direction = volume_delta < -1e-9
        effect_ok = feature_has_shape and expected_direction
    elif operation in {
        "linear_pattern",
        "polar_pattern",
        "mirror",
        "multi_transform",
        "boolean_fuse",
    }:
        expected_direction = abs(volume_delta) > 1e-9
        effect_ok = feature_has_shape and expected_direction
    else:
        expected_direction = abs(volume_delta) > 1e-9
        effect_ok = feature_has_shape and expected_direction
    return {
        "ok": bool(effect_ok),
        "operation": operation,
        "feature_has_shape": bool(feature_has_shape),
        "expected_volume_direction": bool(expected_direction),
        "topology_changed": bool(topology_changed),
        "bound_box_changed": bool(bound_box_changed),
        "body_shape_delta": delta,
    }


def feature_state_summary(feature: Any) -> dict[str, Any]:
    """Snapshot a feature's recompute health.

    Captures FreeCAD's ``State`` flags (``Invalid``/``Touched``/...), whether
    the feature's own shape passes ``isValid()``, and the feature name.
    """
    try:
        state = [str(item) for item in (getattr(feature, "State", []) or [])]
    except Exception:
        state = []
    shape_valid: bool | None = None
    shape_null = True
    try:
        shape = getattr(feature, "Shape", None)
        shape_null = shape is None or bool(shape.isNull())
        if not shape_null:
            shape_valid = bool(shape.isValid())
    except Exception:
        shape_valid = None
    return {
        "name": getattr(feature, "Name", None),
        "label": getattr(feature, "Label", getattr(feature, "Name", None)),
        "type": getattr(feature, "TypeId", None),
        "state": state,
        "marked_invalid": any("Invalid" in item for item in state),
        "shape_null": shape_null,
        "shape_valid": shape_valid,
    }


def invalid_partdesign_tip(body: Any) -> dict[str, Any] | None:
    """Return exact invalid Tip state that must stop downstream feature creation."""
    tip = getattr(body, "Tip", None)
    if tip is None:
        return None
    type_id = str(getattr(tip, "TypeId", ""))
    if type_id == "Sketcher::SketchObject" or type_id in {
        "PartDesign::Plane",
        "PartDesign::Line",
        "PartDesign::Point",
    }:
        return None
    state = feature_state_summary(tip)
    if state.get("marked_invalid") or state.get("shape_valid") is False:
        return state
    if type_id.startswith("PartDesign::") and state.get("shape_null"):
        return state
    base_feature = getattr(tip, "BaseFeature", None)
    operation = partdesign_operation_for_feature(tip)
    if base_feature is not None and operation is not None:
        effect = partdesign_feature_effect(
            operation,
            shape_summary(base_feature),
            shape_summary(tip),
            shape_summary(tip),
        )
        if not effect.get("ok"):
            state["feature_effect"] = effect
            state["effect_invalid"] = True
            return state
    return None


def partdesign_operation_for_feature(feature: Any) -> str | None:
    type_id = str(getattr(feature, "TypeId", ""))
    if type_id.startswith("PartDesign::Additive") and type_id.removeprefix(
        "PartDesign::Additive"
    ) in {"Box", "Cylinder", "Sphere", "Cone", "Ellipsoid", "Torus", "Prism", "Wedge"}:
        return "additive_primitive"
    if type_id.startswith("PartDesign::Subtractive") and type_id.removeprefix(
        "PartDesign::Subtractive"
    ) in {"Box", "Cylinder", "Sphere", "Cone", "Ellipsoid", "Torus", "Prism", "Wedge"}:
        return "subtractive_primitive"
    if type_id == "PartDesign::Boolean":
        return {
            "Fuse": "boolean_fuse",
            "Cut": "boolean_cut",
            "Common": "boolean_common",
        }.get(str(getattr(feature, "Type", "")))
    return {
        "PartDesign::Pad": "pad",
        "PartDesign::Pocket": "pocket",
        "PartDesign::Hole": "hole",
        "PartDesign::Revolution": "revolution",
        "PartDesign::Groove": "groove",
        "PartDesign::AdditiveLoft": "additive_loft",
        "PartDesign::SubtractiveLoft": "subtractive_loft",
        "PartDesign::AdditivePipe": "additive_pipe",
        "PartDesign::SubtractivePipe": "subtractive_pipe",
        "PartDesign::AdditiveHelix": "additive_helix",
        "PartDesign::SubtractiveHelix": "subtractive_helix",
        "PartDesign::LinearPattern": "linear_pattern",
        "PartDesign::PolarPattern": "polar_pattern",
        "PartDesign::Mirrored": "mirror",
        "PartDesign::MultiTransform": "multi_transform",
        "PartDesign::Fillet": "fillet",
        "PartDesign::Chamfer": "chamfer",
        "PartDesign::Draft": "draft",
        "PartDesign::Thickness": "thickness",
    }.get(type_id)


def finalize_partdesign_feature_effect(
    doc: Any,
    body: Any,
    feature: Any,
    operation: str,
    body_shape_before: dict[str, Any],
) -> dict[str, Any]:
    body_shape_after = shape_summary(body)
    feature_shape = shape_summary(feature)
    feature_state = feature_state_summary(feature)
    feature_effect = partdesign_feature_effect(
        operation,
        body_shape_before,
        body_shape_after,
        feature_shape,
    )
    return {
        "body_shape_before": body_shape_before,
        "body_shape_after": body_shape_after,
        "body_shape_delta": feature_effect["body_shape_delta"],
        "feature_shape": feature_shape,
        "feature_state": feature_state,
        "feature_effect": feature_effect,
        "failed_feature_retained": not bool(feature_effect.get("ok")),
    }


def partdesign_feature_response(
    service: Any,
    transaction: dict[str, Any],
    *,
    operation: str,
    profile_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten one native PartDesign mutation and its exact post-recompute state."""
    result = (
        transaction.get("result")
        if isinstance(transaction, dict) and isinstance(transaction.get("result"), dict)
        else {}
    )
    effect = result.get("feature_effect") if isinstance(result, dict) else None
    effect_ok = bool(effect.get("ok")) if isinstance(effect, dict) else False
    transaction_ok = (
        bool(transaction.get("ok")) if isinstance(transaction, dict) else False
    )
    ok = transaction_ok and effect_ok
    native_errors = recompute_errors(transaction)
    body = (
        service._get_partdesign_body(result.get("body")) if result.get("body") else None
    )
    feature_state = result.get("feature_state") or {}
    failure_kind = None
    if not ok:
        if feature_state.get("marked_invalid"):
            failure_kind = "freecad_feature_invalid"
        elif feature_state.get("shape_valid") is False:
            failure_kind = "freecad_shape_invalid"
        elif not bool((effect or {}).get("feature_has_shape")):
            failure_kind = "feature_has_no_shape"
        elif not bool((effect or {}).get("expected_volume_direction")):
            failure_kind = "body_effect_does_not_match_operation"
        elif not transaction_ok:
            failure_kind = "native_operation_error"
        else:
            failure_kind = "feature_has_no_effect"
    response: dict[str, Any] = {
        "ok": ok,
        "operation": operation,
        "mutation": result,
        "document_delta": transaction.get("document_delta") or {},
        "native_errors": native_errors,
        "feature_state": feature_state,
        "feature_effect": effect or {},
        "body_state": service._partdesign_body_summary(body)
        if body is not None
        else None,
        "profile_status": profile_status or {},
        "failed_feature_retained": bool(result.get("feature")) and not ok,
    }
    if not ok:
        response["failure"] = {
            "kind": failure_kind,
            "feature": result.get("feature"),
            "body": result.get("body"),
            "native_errors": native_errors,
        }
        response["error"] = (
            transaction.get("error")
            or (native_errors[-1] if native_errors else None)
            or f"PartDesign {operation} did not produce a valid body effect."
        )
        response["retry_same_call"] = False
    return response


def recompute_errors(transaction: dict[str, Any]) -> list[str]:
    """Extract recompute/report-view error lines from a transaction result."""
    errors: list[str] = []
    if not isinstance(transaction, dict):
        return errors
    report = transaction.get("report_view_errors")
    if isinstance(report, dict):
        errors.extend(str(line) for line in report.get("errors", []) or [])
    transaction_error = transaction.get("error")
    if transaction_error and str(transaction_error) not in errors:
        errors.append(str(transaction_error))
    return errors


def likely_ineffective_feature_cause(
    operation: str,
    feature_effect: dict[str, Any] | None,
    feature_state: dict[str, Any] | None,
    report_errors: list[str] | None,
) -> str | None:
    """Best-effort explanation for why a PartDesign feature had no body effect."""
    joined = " ".join(report_errors or []).lower()
    if "multiple solids" in joined:
        return (
            "The recompute produced multiple solids, which a PartDesign Body "
            "does not allow. Ensure the feature (and every pattern occurrence) "
            "overlaps existing body material so everything fuses into one "
            "connected solid."
        )
    if "disjoint" in joined or "does not intersect" in joined:
        return (
            "The feature shape does not touch the existing body material, so "
            "fusing/cutting it had no effect. Move or resize the profile so it "
            "intersects the body."
        )
    state = feature_state if isinstance(feature_state, dict) else {}
    if state.get("marked_invalid"):
        return (
            "FreeCAD marked the feature Invalid during recompute; its "
            "parameters could not be solved against the current body. Check "
            "the report-view errors above for the solver message."
        )
    effect = feature_effect if isinstance(feature_effect, dict) else {}
    if effect.get("feature_has_shape"):
        if operation in {"pocket", "hole", "groove"}:
            return (
                "The cutting tool shape computed but removed no material - it "
                "likely lies outside the body or spans a region with no "
                "existing material. Verify the profile position, cut direction, "
                "and depth against the body's bounding box."
            )
        return (
            "The feature shape computed but the body's overall shape did not "
            "change - the new material likely coincides exactly with existing "
            "material or fails to fuse into the body."
        )
    return (
        "The feature produced no usable shape of its own; the profile or "
        "parameters likely could not generate geometry. Inspect the source "
        "sketch/profile and the feature parameters."
    )


def describe_ineffective_partdesign_feature(
    operation: str,
    *,
    feature_shape: dict[str, Any] | None,
    feature_effect: dict[str, Any] | None,
    feature_state: dict[str, Any] | None,
    report_errors: list[str] | None,
    lead_in: str | None = None,
) -> tuple[str, str | None]:
    """Compose a diagnostic error message for an ineffective PartDesign feature.

    Returns ``(error_message, likely_cause)``. The message keeps the stable
    lead-in ("was created but did not produce an effective body shape change",
    or the caller-supplied ``lead_in`` override for tools with their own
    stable phrasing) and appends: feature shape stats, Invalid-state flag,
    body delta, captured report-view error lines, and the likely-cause hint.
    """
    parts: list[str] = [
        lead_in
        or (
            f"PartDesign {operation} was created but did not produce an "
            "effective body shape change."
        )
    ]
    shape = feature_shape if isinstance(feature_shape, dict) else {}
    if shape.get("available"):
        parts.append(
            "The feature itself computed a shape "
            f"({int(shape.get('solids', 0) or 0)} solid(s), "
            f"{int(shape.get('faces', 0) or 0)} face(s), "
            f"volume {float(shape.get('volume', 0.0) or 0.0):.3f} mm^3)."
        )
    else:
        parts.append("The feature did not compute a usable shape of its own.")
    state = feature_state if isinstance(feature_state, dict) else {}
    if state.get("marked_invalid"):
        parts.append("FreeCAD marked the feature Invalid after recompute.")
    effect = feature_effect if isinstance(feature_effect, dict) else {}
    delta = effect.get("body_shape_delta")
    if isinstance(delta, dict):
        parts.append(
            "Body shape delta: "
            f"volume {float(delta.get('volume_delta', 0.0) or 0.0):+.3f} mm^3, "
            f"solids {int(delta.get('solids_delta', 0) or 0):+d}, "
            f"faces {int(delta.get('faces_delta', 0) or 0):+d}."
        )
    lines = [str(line) for line in (report_errors or []) if str(line).strip()]
    if lines:
        parts.append("FreeCAD reported: " + " | ".join(lines))
    likely_cause = likely_ineffective_feature_cause(
        operation, feature_effect, feature_state, lines
    )
    if likely_cause:
        parts.append(f"Likely cause: {likely_cause}")
    parts.append(
        "The failed feature was left in the document for inspection or deletion."
    )
    return " ".join(parts), likely_cause


def build_mutation_result(
    transaction: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Standard rich result envelope for mutating service tools.

    Wraps a ``run_freecad_transaction`` result with the uniform keys every
    mutation should expose: ``ok``, ``error`` (when failed), ``transaction``
    (including document before/after/delta snapshots), and flattened
    ``recompute_errors``. Tool-specific payload goes in ``extra``.
    """
    if not isinstance(transaction, dict):
        transaction = {"ok": False, "error": "Invalid transaction result."}
    envelope: dict[str, Any] = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "recompute_errors": recompute_errors(transaction),
        "document_delta": transaction.get("document_delta"),
    }
    if transaction.get("error"):
        envelope["error"] = str(transaction["error"])
    if extra:
        for key, value in extra.items():
            envelope.setdefault(key, value)
    if next_action is not None:
        envelope["next_action"] = next_action
    return envelope


def vector_schema(description: str, *, units: str | None = "mm") -> dict[str, Any]:
    """JSON-schema fragment for an exact ``{x, y, z}`` vector parameter."""
    suffix = f" in {units}" if units else ""
    return {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": f"X component{suffix}."},
            "y": {"type": "number", "description": f"Y component{suffix}."},
            "z": {"type": "number", "description": f"Z component{suffix}."},
        },
        "required": ["x", "y", "z"],
        "additionalProperties": False,
        "description": description,
    }


def parse_vector(value: Any) -> Any:
    """Build an ``App.Vector`` from a validated ``{x, y, z}`` mapping."""
    import FreeCAD as App

    return App.Vector(float(value["x"]), float(value["y"]), float(value["z"]))


def part_feature_result(
    transaction: dict[str, Any],
    *,
    operation: str,
    next_action: str = (
        "Inspect the created object, then continue modeling or capture a screenshot."
    ),
) -> dict[str, Any]:
    """Rich result envelope for Part-workbench feature mutations.

    Extends :func:`build_mutation_result` with the Part contract: the new
    object's shape summary, its recompute-health state, and an ``ok`` verdict
    that requires a computed, valid, non-empty shape.
    """
    envelope = build_mutation_result(transaction, next_action=next_action)
    result = (
        transaction.get("result", {})
        if isinstance(transaction, dict) and isinstance(transaction.get("result"), dict)
        else {}
    )
    feature_state = (
        result.get("feature_state")
        if isinstance(result.get("feature_state"), dict)
        else {}
    )
    shape = result.get("shape") if isinstance(result.get("shape"), dict) else {}
    has_geometry = (
        int(shape.get("faces", 0) or 0) > 0 or int(shape.get("edges", 0) or 0) > 0
    )
    shape_ok = (
        bool(shape.get("available"))
        and has_geometry
        and not feature_state.get("marked_invalid")
        and feature_state.get("shape_valid") is not False
    )
    envelope["ok"] = bool(envelope.get("ok")) and shape_ok
    envelope["operation"] = operation
    envelope["mutation"] = result
    envelope["feature_state"] = feature_state
    envelope["shape"] = shape
    envelope["failed_feature_retained"] = (
        bool(result.get("feature")) and not envelope["ok"]
    )
    if not envelope["ok"] and not envelope.get("error"):
        envelope["error"] = (
            f"Part {operation} was created but did not compute a valid shape. "
            "The failed object was left in the document for inspection or deletion."
        )
        envelope["recoverable"] = True
    return envelope


def build_partdesign_feature_result(
    service: Any,
    transaction: dict[str, Any],
    *,
    operation: str,
    active_sketch: str | None = None,
    profile_status: dict[str, Any] | None = None,
    next_action: str = (
        "Inspect the created feature, then create the next component/detail "
        "or capture a screenshot."
    ),
) -> dict[str, Any]:
    """Rich result envelope for PartDesign feature mutations.

    Extends :func:`build_mutation_result` with the feature-effect contract:
    body shape before/after/delta, feature shape summary, and effectiveness
    verdict.
    """
    if not isinstance(transaction, dict):
        transaction = {"ok": False, "error": "Invalid transaction result."}
    result = (
        transaction.get("result", {})
        if isinstance(transaction.get("result"), dict)
        else {}
    )
    feature_effect = result.get("feature_effect")
    effective = not isinstance(feature_effect, dict) or bool(feature_effect.get("ok"))
    ok = bool(transaction.get("ok")) and effective
    error: str | None = None
    likely_cause: str | None = None
    feature_state = (
        result.get("feature_state")
        if isinstance(result.get("feature_state"), dict)
        else None
    )
    if transaction.get("ok") and not effective:
        error, likely_cause = describe_ineffective_partdesign_feature(
            operation,
            feature_shape=result.get("feature_shape"),
            feature_effect=feature_effect,
            feature_state=feature_state,
            report_errors=recompute_errors(transaction),
        )
    envelope: dict[str, Any] = {
        "ok": ok,
        "transaction": transaction,
        "recompute_errors": recompute_errors(transaction),
        "partdesign": partdesign_summary(service),
        "active_feature": result.get("feature"),
        "feature_shape": result.get("feature_shape"),
        "feature_state": feature_state,
        "likely_cause": likely_cause,
        "body_shape_before": result.get("body_shape_before"),
        "body_shape_after": result.get("body_shape_after"),
        "body_shape_delta": result.get("body_shape_delta"),
        "feature_effect": feature_effect,
        "failed_feature_retained": result.get("failed_feature_retained"),
        "next_action": next_action,
    }
    if error:
        envelope["error"] = error
        envelope["recoverable"] = True
    elif transaction.get("error"):
        envelope["error"] = str(transaction["error"])
    if active_sketch is not None:
        envelope["active_sketch"] = active_sketch
    if profile_status is not None:
        envelope["profile_status"] = profile_status
    return envelope


def spreadsheet_summary(
    service: Any,
    sheet_name: str | None = None,
    max_columns: int = 8,
    max_rows: int = 20,
) -> dict[str, Any]:
    sheet = service._get_spreadsheet(sheet_name)
    sheets = service._spreadsheet_objects()
    if sheet is None:
        return {
            "found": False,
            "requested": sheet_name,
            "sheet_count": len(sheets),
            "sheets": [service._object_summary(item) for item in sheets],
        }

    safe_columns = max(1, min(int(max_columns), 26))
    safe_rows = max(1, min(int(max_rows), 200))
    cells = []
    for column_index in range(1, safe_columns + 1):
        for row in range(1, safe_rows + 1):
            cell = service._cell_name(column_index, row)
            try:
                contents = sheet.getContents(cell)
            except Exception:
                contents = ""
            if contents in ("", None):
                continue
            try:
                value = sheet.get(cell)
            except Exception as exc:
                value = f"<error: {exc}>"
            cells.append(
                {
                    "cell": cell,
                    "contents": service._short_value(contents),
                    "value": service._short_value(value),
                }
            )
    return {
        "found": True,
        "sheet": service._object_summary(sheet),
        "scanned_columns": safe_columns,
        "scanned_rows": safe_rows,
        "non_empty_count": len(cells),
        "cells": cells,
    }


def draft_summary(service: Any) -> dict[str, Any]:
    objects = [service._draft_object_summary(obj) for obj in service._draft_objects()]
    return {"object_count": len(objects), "objects": objects}


def partdesign_summary(service: Any, body_name: str | None = None) -> dict[str, Any]:
    bodies = service._partdesign_bodies()
    body = service._get_partdesign_body(body_name)
    return {
        "body_count": len(bodies),
        "bodies": [service._partdesign_body_summary(item) for item in bodies],
        "selected_body": service._partdesign_body_summary(body) if body else None,
    }


def techdraw_summary(service: Any, page_name: str | None = None) -> dict[str, Any]:
    pages = service._techdraw_pages()
    page = service._get_techdraw_page(page_name)
    return {
        "page_count": len(pages),
        "pages": [service._techdraw_page_summary(item) for item in pages],
        "selected_page": service._techdraw_page_summary(page) if page else None,
    }


def fem_summary(service: Any, analysis_name: str | None = None) -> dict[str, Any]:
    analyses = service._fem_analyses()
    analysis = service._get_fem_analysis(analysis_name)
    return {
        "analysis_count": len(analyses),
        "analyses": [service._fem_analysis_summary(item) for item in analyses],
        "selected_analysis": service._fem_analysis_summary(analysis)
        if analysis
        else None,
    }


def cam_summary(service: Any, job_name: str | None = None) -> dict[str, Any]:
    jobs = service._cam_jobs()
    job = service._get_cam_job(job_name)
    return {
        "job_count": len(jobs),
        "jobs": [service._cam_job_summary(item) for item in jobs],
        "selected_job": service._cam_job_summary(job) if job else None,
    }


def bim_summary(service: Any) -> dict[str, Any]:
    objects = [service._bim_object_summary(obj) for obj in service._bim_objects()]
    return {"object_count": len(objects), "objects": objects}


def assembly_summary(service: Any) -> dict[str, Any]:
    doc = service._active_document()
    assemblies = [service._assembly_summary(obj) for obj in service._assembly_objects()]
    return {
        "document": getattr(doc, "Name", None) if doc else None,
        "assembly_count": len(assemblies),
        "assemblies": assemblies,
    }


def inspection_summary(service: Any) -> dict[str, Any]:
    features = [
        service._inspection_feature_summary(obj)
        for obj in service._inspection_features()
    ]
    candidates = [
        service._document_object_summary(obj)
        for obj in service._inspection_candidates()
    ]
    return {
        "feature_count": len(features),
        "features": features,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def openscad_summary(service: Any) -> dict[str, Any]:
    objects = (
        [
            service._openscad_object_summary(obj)
            for obj in service._active_document().Objects
        ]
        if service._active_document()
        else []
    )
    return {"object_count": len(objects), "objects": objects}


def surface_summary(service: Any) -> dict[str, Any]:
    objects = [
        service._surface_object_summary(obj) for obj in service._surface_objects()
    ]
    return {"object_count": len(objects), "objects": objects}


def reverseengineering_summary(service: Any) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        return {
            "candidate_count": 0,
            "output_count": 0,
            "candidates": [],
            "outputs": [],
        }
    candidates = [
        service._reverseengineering_object_summary(obj)
        for obj in doc.Objects
        if service._is_reverseengineering_candidate(obj)
    ]
    outputs = [
        service._reverseengineering_object_summary(obj)
        for obj in doc.Objects
        if service._is_reverseengineering_output(obj)
    ]
    return {
        "candidate_count": len(candidates),
        "output_count": len(outputs),
        "candidates": candidates,
        "outputs": outputs,
    }


def robot_summary(service: Any) -> dict[str, Any]:
    doc = service._active_document()
    objects = [service._robot_object_summary(obj) for obj in doc.Objects] if doc else []
    robot_like = [obj for obj in objects if obj.get("robot_role")]
    return {
        "object_count": len(objects),
        "robot_object_count": len(robot_like),
        "objects": objects,
    }


def meshpart_summary(service: Any) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        return {
            "document": None,
            "part_candidate_count": 0,
            "mesh_count": 0,
            "part_candidates": [],
            "meshes": [],
        }
    part_candidates = [
        service._part_object_summary(obj)
        for obj in doc.Objects
        if service._is_meshpart_part_candidate(obj)
    ]
    meshes = [
        service._mesh_object_summary(obj)
        for obj in doc.Objects
        if service._is_meshpart_mesh_output(obj)
    ]
    return {
        "document": doc.Name,
        "part_candidate_count": len(part_candidates),
        "mesh_count": len(meshes),
        "part_candidates": part_candidates[:80],
        "meshes": meshes[:80],
    }


def part_summary(service: Any) -> dict[str, Any]:
    objects = [service._part_object_summary(obj) for obj in service._part_objects()]
    return {"object_count": len(objects), "objects": objects}


def mesh_summary(service: Any) -> dict[str, Any]:
    objects = [service._mesh_object_summary(obj) for obj in service._mesh_objects()]
    return {"object_count": len(objects), "objects": objects}


def points_summary(service: Any) -> dict[str, Any]:
    objects = [service._points_object_summary(obj) for obj in service._points_objects()]
    return {"object_count": len(objects), "objects": objects}


def material_summary(service: Any) -> dict[str, Any]:
    objects = [
        service._material_object_summary(obj)
        for obj in service._material_capable_objects()
    ]
    return {"object_count": len(objects), "objects": objects}


def placement_summary(obj: Any) -> dict[str, Any] | None:
    """JSON-safe snapshot of an object's global placement.

    Position in mm plus axis-angle rotation in degrees, matching the
    parameter shape of part.set_placement.
    """
    placement = getattr(obj, "Placement", None)
    if placement is None:
        return None
    try:
        return {
            "position": {
                "x": float(placement.Base.x),
                "y": float(placement.Base.y),
                "z": float(placement.Base.z),
            },
            "rotation_axis": {
                "x": float(placement.Rotation.Axis.x),
                "y": float(placement.Rotation.Axis.y),
                "z": float(placement.Rotation.Axis.z),
            },
            "rotation_angle_degrees": math.degrees(float(placement.Rotation.Angle)),
        }
    except Exception:
        return None


def assembly_joint_group(assembly: Any) -> Any:
    """Return the assembly's native JointGroup, creating it when missing."""
    for child in list(getattr(assembly, "OutList", []) or []):
        if str(getattr(child, "TypeId", "")) == "Assembly::JointGroup":
            return child
    return assembly.newObject("Assembly::JointGroup", "Joints")


ASSEMBLY_SOLVER_MEANINGS: dict[int, str] = {
    0: "solved",
    -1: "solver_error",
    -2: "redundant_constraints",
    -3: "conflicting_constraints",
    -4: "over_constrained",
    -5: "malformed_constraints",
    -6: "no_grounded_component",
}


def assembly_solver_verdict(code: int) -> str:
    """Map the native Assembly::AssemblyObject.solve() return code to a verdict."""
    return ASSEMBLY_SOLVER_MEANINGS.get(int(code), f"unknown_status_{int(code)}")


def is_spreadsheet(obj: Any) -> bool:
    """True when the object is a native Spreadsheet::Sheet."""
    return str(getattr(obj, "TypeId", "")) == "Spreadsheet::Sheet"


def spreadsheet_display_value(value: Any) -> Any:
    """Convert an evaluated spreadsheet cell value to a JSON-safe scalar.

    FreeCAD returns plain numbers/strings for simple cells and Quantity
    objects for cells with units; Quantities are rendered via their
    user-facing string so units stay visible to the model.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    user_string = getattr(value, "UserString", None)
    if user_string is not None:
        return str(user_string)
    return str(value)
