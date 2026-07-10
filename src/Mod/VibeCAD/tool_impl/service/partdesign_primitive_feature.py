# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared native additive and subtractive PartDesign primitive support."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


VECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "z": {"type": "number"},
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}

PLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "origin": VECTOR_SCHEMA,
        "rotation_axis": VECTOR_SCHEMA,
        "rotation_degrees": {"type": "number"},
    },
    "required": ["origin", "rotation_axis", "rotation_degrees"],
    "additionalProperties": False,
}

_POSITIVE = {"type": "number", "exclusiveMinimum": 0}
_NONNEGATIVE = {"type": "number", "minimum": 0}
_AZIMUTH = {"type": "number", "exclusiveMinimum": 0, "maximum": 360}

DEFINITION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "box"},
                "length": _POSITIVE,
                "width": _POSITIVE,
                "height": _POSITIVE,
            },
            "required": ["type", "length", "width", "height"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "cylinder"},
                "radius": _POSITIVE,
                "height": _POSITIVE,
                "angle_degrees": _AZIMUTH,
            },
            "required": ["type", "radius", "height", "angle_degrees"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "sphere"},
                "radius": _POSITIVE,
                "latitude_min_degrees": {"type": "number", "minimum": -90, "maximum": 90},
                "latitude_max_degrees": {"type": "number", "minimum": -90, "maximum": 90},
                "azimuth_degrees": _AZIMUTH,
            },
            "required": [
                "type", "radius", "latitude_min_degrees", "latitude_max_degrees",
                "azimuth_degrees",
            ],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "cone"},
                "bottom_radius": _NONNEGATIVE,
                "top_radius": _NONNEGATIVE,
                "height": _POSITIVE,
                "angle_degrees": _AZIMUTH,
            },
            "required": ["type", "bottom_radius", "top_radius", "height", "angle_degrees"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "ellipsoid"},
                "radius_z": _POSITIVE,
                "radius_x": _POSITIVE,
                "radius_y": _NONNEGATIVE,
                "latitude_min_degrees": {"type": "number", "minimum": -90, "maximum": 90},
                "latitude_max_degrees": {"type": "number", "minimum": -90, "maximum": 90},
                "azimuth_degrees": _AZIMUTH,
            },
            "required": [
                "type", "radius_z", "radius_x", "radius_y", "latitude_min_degrees",
                "latitude_max_degrees", "azimuth_degrees",
            ],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "torus"},
                "major_radius": _POSITIVE,
                "minor_radius": _POSITIVE,
                "profile_min_degrees": {"type": "number", "minimum": -180, "maximum": 180},
                "profile_max_degrees": {"type": "number", "minimum": -180, "maximum": 180},
                "azimuth_degrees": _AZIMUTH,
            },
            "required": [
                "type", "major_radius", "minor_radius", "profile_min_degrees",
                "profile_max_degrees", "azimuth_degrees",
            ],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "prism"},
                "sides": {"type": "integer", "minimum": 3},
                "circumradius": _POSITIVE,
                "height": _POSITIVE,
            },
            "required": ["type", "sides", "circumradius", "height"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "wedge"},
                "x_min": {"type": "number"},
                "y_min": {"type": "number"},
                "z_min": {"type": "number"},
                "x2_min": {"type": "number"},
                "z2_min": {"type": "number"},
                "x_max": {"type": "number"},
                "y_max": {"type": "number"},
                "z_max": {"type": "number"},
                "x2_max": {"type": "number"},
                "z2_max": {"type": "number"},
            },
            "required": [
                "type", "x_min", "y_min", "z_min", "x2_min", "z2_min", "x_max",
                "y_max", "z_max", "x2_max", "z2_max",
            ],
            "additionalProperties": False,
        },
    ]
}

PARAMETERS = {
    "type": "object",
    "properties": {
        "body_name": {"type": "string"},
        "label": {"type": "string"},
        "definition": DEFINITION_SCHEMA,
        "placement": PLACEMENT_SCHEMA,
        "refine": {"type": "boolean"},
    },
    "required": ["body_name", "label", "definition", "placement", "refine"],
    "additionalProperties": False,
}

_NATIVE_TYPE = {
    "box": "Box",
    "cylinder": "Cylinder",
    "sphere": "Sphere",
    "cone": "Cone",
    "ellipsoid": "Ellipsoid",
    "torus": "Torus",
    "prism": "Prism",
    "wedge": "Wedge",
}

_PROPERTY_MAP = {
    "box": {"length": "Length", "width": "Width", "height": "Height"},
    "cylinder": {"radius": "Radius", "height": "Height", "angle_degrees": "Angle"},
    "sphere": {
        "radius": "Radius",
        "latitude_min_degrees": "Angle1",
        "latitude_max_degrees": "Angle2",
        "azimuth_degrees": "Angle3",
    },
    "cone": {
        "bottom_radius": "Radius1",
        "top_radius": "Radius2",
        "height": "Height",
        "angle_degrees": "Angle",
    },
    "ellipsoid": {
        "radius_z": "Radius1",
        "radius_x": "Radius2",
        "radius_y": "Radius3",
        "latitude_min_degrees": "Angle1",
        "latitude_max_degrees": "Angle2",
        "azimuth_degrees": "Angle3",
    },
    "torus": {
        "major_radius": "Radius1",
        "minor_radius": "Radius2",
        "profile_min_degrees": "Angle1",
        "profile_max_degrees": "Angle2",
        "azimuth_degrees": "Angle3",
    },
    "prism": {"sides": "Polygon", "circumradius": "Circumradius", "height": "Height"},
    "wedge": {
        "x_min": "Xmin",
        "y_min": "Ymin",
        "z_min": "Zmin",
        "x2_min": "X2min",
        "z2_min": "Z2min",
        "x_max": "Xmax",
        "y_max": "Ymax",
        "z_max": "Zmax",
        "x2_max": "X2max",
        "z2_max": "Z2max",
    },
}


def run(
    service: Any,
    *,
    operation: str,
    body_name: str,
    label: str,
    definition: dict[str, Any],
    placement: dict[str, Any],
    refine: bool,
) -> dict[str, Any]:
    body = service._get_partdesign_body(str(body_name or "").strip())
    if body is None:
        return _invalid(f"Body not found by exact internal name: {body_name}")
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    definition_state = _validate_definition(definition)
    if not definition_state.get("ok"):
        return definition_state
    placement_state = _validate_placement(placement)
    if not placement_state.get("ok"):
        return placement_state
    tip_block = domain_runtime.invalid_partdesign_tip(body)
    if tip_block is not None:
        return _invalid(
            "The target Body has an invalid or zero-effect Tip.",
            tip_state=tip_block,
        )
    body_shape_before = domain_runtime.shape_summary(body)
    if operation == "subtractive_primitive" and int(body_shape_before.get("solids", 0) or 0) == 0:
        return _invalid(f"Body {body.Name} has no solid for a subtractive primitive.")

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        target_body = service._get_partdesign_body(body.Name)
        if doc is None or target_body is None:
            raise RuntimeError("Document or target Body no longer exists.")
        prefix = "Additive" if operation == "additive_primitive" else "Subtractive"
        primitive_name = _NATIVE_TYPE[definition_state["type"]]
        primitive = target_body.newObject(
            f"PartDesign::{prefix}{primitive_name}",
            f"{prefix}{primitive_name}",
        )
        primitive.Label = clean_label
        for source_name, property_name in _PROPERTY_MAP[definition_state["type"]].items():
            setattr(primitive, property_name, definition_state["values"][source_name])
        primitive.Placement = App.Placement(
            App.Vector(*placement_state["origin"]),
            App.Rotation(
                App.Vector(*placement_state["rotation_axis"]),
                placement_state["rotation_degrees"],
            ),
        )
        primitive.Refine = bool(refine)
        target_body.Tip = primitive
        doc.recompute()
        effect = domain_runtime.finalize_partdesign_feature_effect(
            doc,
            target_body,
            primitive,
            operation,
            body_shape_before,
        )
        return {
            "document": doc.Name,
            "body": target_body.Name,
            "feature": primitive.Name,
            "feature_label": primitive.Label,
            "feature_type": primitive.TypeId,
            "primitive_type": definition_state["type"],
            "parameters": {
                source_name: _native_number(getattr(primitive, property_name))
                for source_name, property_name in _PROPERTY_MAP[definition_state["type"]].items()
            },
            "placement": service._placement_summary(primitive.Placement),
            "refine": bool(primitive.Refine),
            "body_group": [item.Name for item in list(target_body.Group)],
            "body_tip": getattr(getattr(target_body, "Tip", None), "Name", None),
            "base_feature": getattr(getattr(primitive, "BaseFeature", None), "Name", None),
            **effect,
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign {operation}: {clean_label}",
        create,
    )
    return domain_runtime.partdesign_feature_response(
        service,
        transaction,
        operation=operation,
    )


def _validate_definition(definition: Any) -> dict[str, Any]:
    if not isinstance(definition, dict):
        return _invalid("definition must be an object.")
    kind = str(definition.get("type") or "")
    if kind not in _PROPERTY_MAP:
        return _invalid(f"Unsupported primitive definition type: {kind}")
    try:
        values = {
            name: int(definition[name]) if name == "sides" else float(definition[name])
            for name in _PROPERTY_MAP[kind]
        }
    except (KeyError, TypeError, ValueError) as exc:
        return _invalid(f"Primitive definition has a missing or non-numeric value: {exc}")
    if kind == "box" and any(values[name] <= 0 for name in ("length", "width", "height")):
        return _invalid("Box length, width, and height must be positive.")
    if kind == "cylinder" and (values["radius"] <= 0 or values["height"] <= 0):
        return _invalid("Cylinder radius and height must be positive.")
    if kind in {"sphere", "ellipsoid"}:
        if values["latitude_min_degrees"] >= values["latitude_max_degrees"]:
            return _invalid("Latitude minimum must be less than latitude maximum.")
    if kind == "sphere" and values["radius"] <= 0:
        return _invalid("Sphere radius must be positive.")
    if kind == "cone":
        if values["bottom_radius"] < 0 or values["top_radius"] < 0:
            return _invalid("Cone radii cannot be negative.")
        if values["bottom_radius"] == 0 and values["top_radius"] == 0:
            return _invalid("At least one cone radius must be positive.")
        if values["height"] <= 0:
            return _invalid("Cone height must be positive.")
    if kind == "ellipsoid" and (
        values["radius_z"] <= 0 or values["radius_x"] <= 0 or values["radius_y"] < 0
    ):
        return _invalid("Ellipsoid Z/X radii must be positive and Y radius cannot be negative.")
    if kind == "torus":
        if values["major_radius"] <= 0 or values["minor_radius"] <= 0:
            return _invalid("Torus radii must be positive.")
        if values["profile_min_degrees"] >= values["profile_max_degrees"]:
            return _invalid("Torus profile minimum must be less than profile maximum.")
    if kind == "prism" and (
        values["sides"] < 3 or values["circumradius"] <= 0 or values["height"] <= 0
    ):
        return _invalid("Prism requires at least 3 sides and positive circumradius/height.")
    if kind == "wedge" and not (
        values["x_max"] > values["x_min"]
        and values["y_max"] > values["y_min"]
        and values["z_max"] > values["z_min"]
        and values["x2_max"] >= values["x2_min"]
        and values["z2_max"] >= values["z2_min"]
    ):
        return _invalid("Wedge outer bounds must increase and x2/z2 maximums cannot precede minimums.")
    if kind in {"cylinder", "cone"} and not 0 < values["angle_degrees"] <= 360:
        return _invalid("Primitive angle_degrees must be greater than 0 and at most 360.")
    if kind in {"sphere", "ellipsoid", "torus"} and not 0 < values["azimuth_degrees"] <= 360:
        return _invalid("Primitive azimuth_degrees must be greater than 0 and at most 360.")
    return {"ok": True, "type": kind, "values": values}


def _validate_placement(placement: Any) -> dict[str, Any]:
    if not isinstance(placement, dict):
        return _invalid("placement must be an object.")
    try:
        origin = tuple(float(placement["origin"][key]) for key in ("x", "y", "z"))
        axis = tuple(float(placement["rotation_axis"][key]) for key in ("x", "y", "z"))
        angle = float(placement["rotation_degrees"])
    except (KeyError, TypeError, ValueError):
        return _invalid("placement requires numeric origin, rotation_axis, and rotation_degrees.")
    if sum(value * value for value in axis) <= 1e-18:
        return _invalid("placement.rotation_axis must be non-zero.")
    return {
        "ok": True,
        "origin": origin,
        "rotation_axis": axis,
        "rotation_degrees": angle,
    }


def _native_number(value: Any) -> int | float:
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
