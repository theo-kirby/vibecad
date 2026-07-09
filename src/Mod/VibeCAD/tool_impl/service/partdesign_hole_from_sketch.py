# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``partdesign.hole_from_sketch``."""

from __future__ import annotations

from typing import Any

from . import domain_runtime
from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'contextual': True,
 'description': 'Create a native PartDesign Hole feature from an existing sketch, '
                'equivalent to using the PartDesign Hole tool after selecting a '
                'sketch with hole center/profile geometry.',
 'name': 'partdesign.hole_from_sketch',
 'parameters': {'properties': {'countersink_angle': {'description': 'Countersink '
                                                                    'angle in degrees '
                                                                    'when hole_cut_type '
                                                                    'is 2.',
                                                     'type': 'number'},
                               'depth': {'description': 'Hole depth in mm when depth_type is 0.',
                                         'type': 'number'},
                               'depth_type': {'description': 'Native Hole DepthType '
                                                            'integer. 0 is blind '
                                                            'depth; 1 is through all.',
                                              'type': 'integer'},
                               'diameter': {'description': 'Hole diameter in mm.',
                                            'type': 'number'},
                               'drill_point': {'description': 'Native DrillPoint '
                                                             'integer. 0 is flat; '
                                                             '1 is angled.',
                                               'type': 'integer'},
                               'drill_point_angle': {'description': 'Drill tip angle in degrees when drill_point is 1.',
                                                     'type': 'number'},
                               'hole_cut_depth': {'description': 'Counterbore depth '
                                                                'when hole_cut_type '
                                                                'is 1.',
                                                  'type': 'number'},
                               'hole_cut_diameter': {'description': 'Counterbore or '
                                                                   'countersink top '
                                                                   'diameter.',
                                                     'type': 'number'},
                               'hole_cut_type': {'description': 'Native HoleCutType '
                                                               'integer. 0 plain, '
                                                               '1 counterbore, '
                                                               '2 countersink.',
                                                 'type': 'integer'},
                               'label': {'type': 'string'},
                               'refine': {'type': 'boolean'},
                               'sketch_map_reversed': {'description': 'Optional native '
                                                                      'Sketch MapReversed '
                                                                      'setting before '
                                                                      'creating the '
                                                                      'Hole. Use when '
                                                                      'hole direction '
                                                                      'needs to follow '
                                                                      'the opposite side '
                                                                      'of the support '
                                                                      'plane.',
                                                       'type': 'boolean'},
                               'sketch_name': {'description': 'Sketch (name or label) holding the hole center points/circles.',
                                               'type': 'string'},
                               'tapered': {'description': 'Enable a tapered hole.',
                                           'type': 'boolean'},
                               'tapered_angle': {'description': 'Taper angle in degrees when tapered is true.',
                                                 'type': 'number'},
                               'thread_type': {'description': 'Native ThreadType '
                                                             'integer. Use 0 for '
                                                             'plain unthreaded holes.',
                                               'type': 'integer'}},
                'required': ['sketch_name', 'diameter', 'depth_type', 'hole_cut_type'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartDesignWorkbench'}


def run(
    service,
    sketch_name: str,
    label: str = "VibeCAD Hole",
    diameter: float | None = None,
    depth: float | None = None,
    depth_type: int | None = None,
    hole_cut_type: int | None = None,
    hole_cut_diameter: float | None = None,
    hole_cut_depth: float | None = None,
    countersink_angle: float = 90.0,
    drill_point: int = 0,
    drill_point_angle: float = 118.0,
    tapered: bool = False,
    tapered_angle: float = 90.0,
    thread_type: int = 0,
    refine: bool | None = None,
    sketch_map_reversed: bool | None = None,
) -> dict[str, Any]:
    sketch = service._get_sketch(sketch_name)
    if sketch is None:
        return {"ok": False, "error": "Sketch not found.", "requested": sketch_name}
    if diameter is None:
        return {"ok": False, "error": "diameter is required.", "retry_same_call": False}
    if depth_type is None:
        return {"ok": False, "error": "depth_type is required.", "retry_same_call": False}
    if hole_cut_type is None:
        return {"ok": False, "error": "hole_cut_type is required.", "retry_same_call": False}
    if float(diameter) <= 0:
        return {"ok": False, "error": "Hole diameter must be positive."}
    if int(hole_cut_type) not in {0, 1, 2}:
        return {"ok": False, "error": "hole_cut_type must be 0 plain, 1 counterbore, or 2 countersink."}
    if int(depth_type) not in {0, 1}:
        return {"ok": False, "error": "depth_type must be 0 blind depth or 1 through all."}
    if int(depth_type) == 0:
        if depth is None:
            return {"ok": False, "error": "depth is required for blind holes.", "retry_same_call": False}
        if float(depth) <= 0:
            return {"ok": False, "error": "Blind hole depth must be positive."}
    effective_depth = float(depth) if depth is not None else 0.0
    if int(hole_cut_type) == 1:
        if hole_cut_diameter is None:
            return {"ok": False, "error": "hole_cut_diameter is required for counterbore holes.", "retry_same_call": False}
        if hole_cut_depth is None:
            return {"ok": False, "error": "hole_cut_depth is required for counterbore holes.", "retry_same_call": False}
        if float(hole_cut_diameter) <= float(diameter):
            return {"ok": False, "error": "Counterbore diameter must be greater than hole diameter."}
        if float(hole_cut_depth) <= 0:
            return {"ok": False, "error": "Counterbore depth must be positive."}
    if int(hole_cut_type) == 2:
        if hole_cut_diameter is None:
            return {"ok": False, "error": "hole_cut_diameter is required for countersink holes.", "retry_same_call": False}
        if float(hole_cut_diameter) <= float(diameter):
            return {"ok": False, "error": "Countersink top diameter must be greater than hole diameter."}
        if float(countersink_angle) <= 0 or float(countersink_angle) >= 180:
            return {"ok": False, "error": "Countersink angle must be greater than 0 and less than 180 degrees."}

    def _hole() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_sketch = service._get_sketch(sketch.Name)
        if target_sketch is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        if sketch_map_reversed is not None and hasattr(target_sketch, "MapReversed"):
            target_sketch.MapReversed = bool(sketch_map_reversed)
            doc.recompute()
        body = service._partdesign_body_for_feature(target_sketch)
        if body is None:
            raise RuntimeError("No PartDesign Body found for hole.")
        body_shape_before = domain_runtime.shape_summary(body)
        hole = doc.addObject("PartDesign::Hole", "VibeCAD_Hole")
        hole.Label = label or "VibeCAD Hole"
        hole.Profile = target_sketch
        body.addObject(hole)
        hole.Diameter = float(diameter)
        hole.Depth = effective_depth
        hole.DepthType = int(depth_type)
        hole.ThreadType = int(thread_type)
        hole.HoleCutType = int(hole_cut_type)
        if hole_cut_diameter is not None:
            hole.HoleCutDiameter = float(hole_cut_diameter)
        if hole_cut_depth is not None:
            hole.HoleCutDepth = float(hole_cut_depth)
        hole.HoleCutCountersinkAngle = float(countersink_angle)
        hole.DrillPoint = int(drill_point)
        hole.DrillPointAngle = float(drill_point_angle)
        hole.Tapered = 1 if tapered else 0
        hole.TaperedAngle = float(tapered_angle)
        if refine is not None:
            hole.Refine = bool(refine)
        body.Tip = hole
        doc.recompute()
        hole_name = hole.Name
        hole_label = getattr(hole, "Label", hole.Name)
        hole_type = getattr(hole, "TypeId", "")
        hole_diameter = float(hole.Diameter)
        hole_depth = float(hole.Depth)
        hole_depth_type_value = _property_value(hole, "DepthType")
        hole_cut_type_value = _property_value(hole, "HoleCutType")
        hole_cut_diameter_value = _float_property(hole, "HoleCutDiameter")
        hole_cut_depth_value = _float_property(hole, "HoleCutDepth")
        countersink_angle_value = _float_property(hole, "HoleCutCountersinkAngle")
        drill_point_value = _property_value(hole, "DrillPoint")
        drill_point_angle_value = _float_property(hole, "DrillPointAngle")
        tapered_value = bool(getattr(hole, "Tapered", False))
        tapered_angle_value = _float_property(hole, "TaperedAngle")
        effect = domain_runtime.finalize_partdesign_feature_effect(
            doc,
            body,
            hole,
            "hole",
            body_shape_before,
        )
        return {
            "document": doc.Name,
            "body": body.Name,
            "sketch": target_sketch.Name,
            "feature": hole_name,
            "label": hole_label,
            "type": hole_type,
            "diameter": hole_diameter,
            "depth": hole_depth,
            "depth_type": hole_depth_type_value,
            "hole_cut_type": hole_cut_type_value,
            "hole_cut_diameter": hole_cut_diameter_value,
            "hole_cut_depth": hole_cut_depth_value,
            "countersink_angle": countersink_angle_value,
            "drill_point": drill_point_value,
            "drill_point_angle": drill_point_angle_value,
            "tapered": tapered_value,
            "tapered_angle": tapered_angle_value,
            "sketch_map_reversed": bool(getattr(target_sketch, "MapReversed", False)),
            **effect,
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign hole from sketch: {getattr(sketch, 'Label', sketch.Name)}",
        _hole,
    )
    transaction_result = transaction.get("result", {}) if isinstance(transaction.get("result"), dict) else {}
    feature_effect = transaction_result.get("feature_effect")
    effective = not isinstance(feature_effect, dict) or bool(feature_effect.get("ok"))
    ok = bool(transaction.get("ok")) and effective
    error = None
    likely_cause = None
    if not transaction.get("ok"):
        error = transaction.get("error") or "PartDesign Hole failed."
    elif not effective:
        error, likely_cause = domain_runtime.describe_ineffective_partdesign_feature(
            "hole",
            feature_shape=transaction_result.get("feature_shape"),
            feature_effect=feature_effect,
            feature_state=transaction_result.get("feature_state"),
            report_errors=domain_runtime.recompute_errors(transaction),
            rolled_back=bool(transaction_result.get("rolled_back_feature")),
            lead_in="PartDesign Hole was created but did not remove material from the body.",
        )
    return {
        "ok": ok,
        **({"error": error, "recoverable": True} if error else {}),
        "transaction": transaction,
        "partdesign": domain_runtime.partdesign_summary(service),
        "active_feature": transaction_result.get("feature"),
        "feature_shape": transaction_result.get("feature_shape"),
        "feature_state": transaction_result.get("feature_state"),
        "likely_cause": likely_cause,
        "body_shape_before": transaction_result.get("body_shape_before"),
        "body_shape_after": transaction_result.get("body_shape_after"),
        "body_shape_delta": transaction_result.get("body_shape_delta"),
        "feature_effect": feature_effect,
        "rolled_back_feature": transaction_result.get("rolled_back_feature"),
        "body_shape_after_rollback": transaction_result.get("body_shape_after_rollback"),
        "sketcher": service.sketcher_summary(getattr(sketch, "Name", None)),
        "next_action": "Inspect the hole feature, then add further details or capture a screenshot.",
    }


def _float_property(obj, name: str) -> float | None:
    try:
        return float(getattr(obj, name))
    except Exception:
        return None


def _property_value(obj, name: str):
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
