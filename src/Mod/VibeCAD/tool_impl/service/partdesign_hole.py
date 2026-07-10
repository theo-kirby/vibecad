# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Hole tool."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_THREAD_TYPES = [
    "ISOMetricProfile",
    "ISOMetricFineProfile",
    "UNC",
    "UNF",
    "UNEF",
    "NPT",
    "BSP",
    "BSW",
    "BSF",
    "ISOTyre",
]

_DEPTH_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "dimension"},
                "value": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["type", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"type": {"const": "through_all"}},
            "required": ["type"],
            "additionalProperties": False,
        },
    ]
}

_CUT_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"type": {"const": "none"}},
            "required": ["type"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "counterbore"},
                "diameter": {"type": "number", "exclusiveMinimum": 0},
                "depth": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["type", "diameter", "depth"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "countersink"},
                "diameter": {"type": "number", "exclusiveMinimum": 0},
                "angle_degrees": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "exclusiveMaximum": 180,
                },
            },
            "required": ["type", "diameter", "angle_degrees"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "counterdrill"},
                "diameter": {"type": "number", "exclusiveMinimum": 0},
                "depth": {"type": "number", "exclusiveMinimum": 0},
                "angle_degrees": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "exclusiveMaximum": 180,
                },
            },
            "required": ["type", "diameter", "depth", "angle_degrees"],
            "additionalProperties": False,
        },
    ]
}

_DRILL_POINT_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "flat"},
                "depth_includes_tip": {"type": "boolean"},
            },
            "required": ["type", "depth_includes_tip"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "angled"},
                "angle_degrees": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "exclusiveMaximum": 180,
                },
                "depth_includes_tip": {"type": "boolean"},
            },
            "required": ["type", "angle_degrees", "depth_includes_tip"],
            "additionalProperties": False,
        },
    ]
}

_TAPER_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"enabled": {"const": False}},
            "required": ["enabled"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "enabled": {"const": True},
                "angle_degrees": {"type": "number"},
            },
            "required": ["enabled", "angle_degrees"],
            "additionalProperties": False,
        },
    ]
}

_THREAD_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"enabled": {"const": False}},
            "required": ["enabled"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "enabled": {"const": True},
                "standard": {"type": "string", "enum": _THREAD_TYPES},
                "size": {"type": "string"},
                "class": {"type": "string"},
                "fit": {"type": "string"},
                "direction": {"type": "string", "enum": ["right", "left"]},
                "depth_type": {
                    "type": "string",
                    "enum": ["hole_depth", "dimension", "tapped_din76"],
                },
                "depth": {"type": "number", "exclusiveMinimum": 0},
                "model_thread": {"type": "boolean"},
                "cosmetic_thread": {"type": "boolean"},
                "custom_clearance": {"type": "number", "minimum": 0},
            },
            "required": [
                "enabled",
                "standard",
                "size",
                "direction",
                "depth_type",
                "model_thread",
                "cosmetic_thread",
            ],
            "additionalProperties": False,
        },
    ]
}

TOOL_SPEC = {
    "name": "partdesign.hole",
    "description": (
        "Create one native PartDesign Hole from circular geometry in an exact sketch owned by "
        "a solid Body. Uses named depth, counterbore/countersink, drill-point, taper, and thread "
        "settings rather than FreeCAD enum integers; requested thread size/class/fit are validated "
        "against this FreeCAD installation."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "profile_name": {"type": "string"},
            "label": {"type": "string"},
            "diameter": {"type": "number", "exclusiveMinimum": 0},
            "depth": _DEPTH_SCHEMA,
            "cut": _CUT_SCHEMA,
            "drill_point": _DRILL_POINT_SCHEMA,
            "taper": _TAPER_SCHEMA,
            "thread": _THREAD_SCHEMA,
            "reversed": {"type": "boolean"},
            "midplane": {"type": "boolean"},
            "refine": {"type": "boolean"},
        },
        "required": [
            "profile_name",
            "label",
            "diameter",
            "depth",
            "cut",
            "drill_point",
            "taper",
            "thread",
            "reversed",
            "midplane",
            "refine",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    profile_name: str,
    label: str,
    diameter: float,
    depth: dict[str, Any],
    cut: dict[str, Any],
    drill_point: dict[str, Any],
    taper: dict[str, Any],
    thread: dict[str, Any],
    reversed: bool,
    midplane: bool,
    refine: bool,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if float(diameter) <= 0:
        return _invalid("diameter must be positive.")
    profile = service._get_sketch(str(profile_name or ""))
    if profile is None:
        return _invalid(
            f"Hole profile not found by exact internal name: {profile_name}"
        )
    body = service._partdesign_body_for_feature(profile)
    if body is None:
        return _invalid(
            f"Sketch {profile.Name} is not owned by exactly one PartDesign Body."
        )
    tip_block = domain_runtime.invalid_partdesign_tip(body)
    if tip_block is not None:
        return {
            "ok": False,
            "error": "The profile Body has an invalid or zero-effect Tip.",
            "tip_state": tip_block,
            "retry_same_call": False,
        }
    body_shape_before = domain_runtime.shape_summary(body)
    if int(body_shape_before.get("solids", 0) or 0) == 0:
        return _invalid(
            f"Body {body.Name} has no solid for a Hole to remove material from.",
            body_shape=body_shape_before,
        )
    profile_status = service._sketch_profile_status(profile)
    if not profile_status.get("ready_for_hole_centers"):
        return {
            "ok": False,
            "error": (
                f"Sketch {profile.Name} is not a valid Hole profile; all non-construction "
                "geometry must be circles or circular arcs."
            ),
            "profile_status": profile_status,
            "retry_same_call": False,
        }
    config = _validate_configuration(diameter, depth, cut, drill_point, taper, thread)
    if not config.get("ok"):
        return config

    def create_hole() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target_profile = service._get_sketch(profile.Name)
        if target_profile is None:
            raise RuntimeError(f"Hole profile no longer exists: {profile.Name}")
        target_body = service._partdesign_body_for_feature(target_profile)
        if target_body is None or target_body.Name != body.Name:
            raise RuntimeError(f"Hole profile ownership changed for {profile.Name}.")

        hole = target_body.newObject("PartDesign::Hole", "Hole")
        hole.Label = clean_label
        hole.Profile = target_profile
        hole.Diameter = float(diameter)
        hole.DepthType = config["depth_type"]
        if config.get("depth_value") is not None:
            hole.Depth = config["depth_value"]
        hole.HoleCutType = config["cut_type"]
        hole.HoleCutCustomValues = config["cut_type"] != "None"
        if config.get("cut_diameter") is not None:
            hole.HoleCutDiameter = config["cut_diameter"]
        if config.get("cut_depth") is not None:
            hole.HoleCutDepth = config["cut_depth"]
        if config.get("cut_angle") is not None:
            hole.HoleCutCountersinkAngle = config["cut_angle"]
        hole.DrillPoint = config["drill_point"]
        if config.get("drill_angle") is not None:
            hole.DrillPointAngle = config["drill_angle"]
        hole.DrillForDepth = bool(config["depth_includes_tip"])
        hole.Tapered = bool(config["taper_enabled"])
        hole.TaperedAngle = float(config["taper_angle"])
        _apply_thread(hole, config["thread"])
        hole.Reversed = bool(reversed)
        hole.Midplane = bool(midplane)
        hole.Refine = bool(refine)
        target_body.Tip = hole
        doc.recompute()
        effect = domain_runtime.finalize_partdesign_feature_effect(
            doc,
            target_body,
            hole,
            "hole",
            body_shape_before,
        )
        return {
            "document": doc.Name,
            "body": target_body.Name,
            "profile": target_profile.Name,
            "feature": hole.Name,
            "feature_label": hole.Label,
            "feature_type": hole.TypeId,
            "diameter": float(hole.Diameter),
            "depth_type": str(hole.DepthType),
            "depth": float(hole.Depth),
            "cut_type": str(hole.HoleCutType),
            "thread_type": str(hole.ThreadType),
            "thread_size": str(hole.ThreadSize),
            "thread_class": str(hole.ThreadClass),
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
            "base_feature": getattr(getattr(hole, "BaseFeature", None), "Name", None),
            **effect,
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign hole: {clean_label}",
        create_hole,
    )
    return domain_runtime.partdesign_feature_response(
        service,
        transaction,
        operation="hole",
        profile_status=profile_status,
    )


def _validate_configuration(
    diameter: float,
    depth: dict[str, Any],
    cut: dict[str, Any],
    drill_point: dict[str, Any],
    taper: dict[str, Any],
    thread: dict[str, Any],
) -> dict[str, Any]:
    if not all(isinstance(item, dict) for item in (depth, cut, drill_point, taper, thread)):
        return _invalid("depth, cut, drill_point, taper, and thread must be objects.")
    depth_type = {"dimension": "Dimension", "through_all": "ThroughAll"}.get(
        str(depth.get("type") or "")
    )
    if depth_type is None:
        return _invalid("depth.type must be dimension or through_all.")
    depth_value = depth.get("value")
    if depth_type == "Dimension" and (depth_value is None or float(depth_value) <= 0):
        return _invalid("depth.value must be positive for dimension depth.")

    cut_type = {
        "none": "None",
        "counterbore": "Counterbore",
        "countersink": "Countersink",
        "counterdrill": "Counterdrill",
    }.get(str(cut.get("type") or ""))
    if cut_type is None:
        return _invalid("Unknown cut.type.")
    cut_diameter = cut.get("diameter")
    cut_depth = cut.get("depth")
    cut_angle = cut.get("angle_degrees")
    if cut_type != "None":
        if cut_diameter is None or float(cut_diameter) <= float(diameter):
            return _invalid("cut.diameter must be greater than the hole diameter.")
    if cut_type in {"Counterbore", "Counterdrill"} and (
        cut_depth is None or float(cut_depth) <= 0
    ):
        return _invalid(f"cut.depth must be positive for {cut_type}.")
    if cut_type in {"Countersink", "Counterdrill"} and (
        cut_angle is None or not (0 < float(cut_angle) < 180)
    ):
        return _invalid(f"cut.angle_degrees is required for {cut_type}.")

    drill_type = {"flat": "Flat", "angled": "Angled"}.get(
        str(drill_point.get("type") or "")
    )
    if drill_type is None:
        return _invalid("drill_point.type must be flat or angled.")
    drill_angle = drill_point.get("angle_degrees")
    if drill_type == "Angled" and (
        drill_angle is None or not (0 < float(drill_angle) < 180)
    ):
        return _invalid("drill_point.angle_degrees is required for an angled point.")

    taper_enabled = bool(taper.get("enabled"))
    taper_angle = float(taper.get("angle_degrees", 0.0) or 0.0)
    if taper_enabled and not (-89 < taper_angle < 89):
        return _invalid("taper.angle_degrees must be greater than -89 and less than 89.")

    thread_enabled = bool(thread.get("enabled"))
    if thread_enabled:
        standard = str(thread.get("standard") or "")
        size = str(thread.get("size") or "")
        if standard not in _THREAD_TYPES or not size:
            return _invalid("Enabled thread requires a supported standard and non-empty size.")
        thread_depth_type = {
            "hole_depth": "Hole Depth",
            "dimension": "Dimension",
            "tapped_din76": "Tapped (DIN76)",
        }.get(str(thread.get("depth_type") or ""))
        if thread_depth_type is None:
            return _invalid("Unknown thread.depth_type.")
        thread_depth = thread.get("depth")
        if thread_depth_type == "Dimension" and (
            thread_depth is None or float(thread_depth) <= 0
        ):
            return _invalid("thread.depth must be positive for dimension thread depth.")
    else:
        standard = "None"
        size = "---"
        thread_depth_type = "Hole Depth"
        thread_depth = None

    return {
        "ok": True,
        "depth_type": depth_type,
        "depth_value": float(depth_value) if depth_value is not None else None,
        "cut_type": cut_type,
        "cut_diameter": float(cut_diameter) if cut_diameter is not None else None,
        "cut_depth": float(cut_depth) if cut_depth is not None else None,
        "cut_angle": float(cut_angle) if cut_angle is not None else None,
        "drill_point": drill_type,
        "drill_angle": float(drill_angle) if drill_angle is not None else None,
        "depth_includes_tip": bool(drill_point.get("depth_includes_tip")),
        "taper_enabled": taper_enabled,
        "taper_angle": taper_angle,
        "thread": {
            "enabled": thread_enabled,
            "standard": standard,
            "size": size,
            "class": str(thread.get("class") or ""),
            "fit": str(thread.get("fit") or ""),
            "direction": "Right" if str(thread.get("direction")) == "right" else "Left",
            "depth_type": thread_depth_type,
            "depth": float(thread_depth) if thread_depth is not None else None,
            "model_thread": bool(thread.get("model_thread")),
            "cosmetic_thread": bool(thread.get("cosmetic_thread")),
            "custom_clearance": thread.get("custom_clearance"),
        },
    }


def _apply_thread(hole: Any, config: dict[str, Any]) -> None:
    if not config["enabled"]:
        hole.Threaded = False
        hole.ThreadType = "None"
        hole.ModelThread = False
        hole.CosmeticThread = False
        return
    hole.Threaded = True
    hole.ThreadType = config["standard"]
    _set_native_enum(hole, "ThreadSize", config["size"])
    if config["class"]:
        _set_native_enum(hole, "ThreadClass", config["class"])
    if config["fit"]:
        _set_native_enum(hole, "ThreadFit", config["fit"])
    hole.ThreadDirection = config["direction"]
    hole.ThreadDepthType = config["depth_type"]
    if config["depth"] is not None:
        hole.ThreadDepth = config["depth"]
    hole.ModelThread = config["model_thread"]
    hole.CosmeticThread = config["cosmetic_thread"]
    if config["custom_clearance"] is not None:
        hole.UseCustomThreadClearance = True
        hole.CustomThreadClearance = float(config["custom_clearance"])
    else:
        hole.UseCustomThreadClearance = False


def _set_native_enum(obj: Any, property_name: str, value: str) -> None:
    choices = list(obj.getEnumerationsOfProperty(property_name) or [])
    if value not in choices:
        raise ValueError(
            f"{property_name} '{value}' is unavailable. Native choices: {choices}"
        )
    setattr(obj, property_name, value)


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "retry_same_call": False,
        **details,
    }
