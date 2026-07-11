# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part primitive solid."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "part.create_primitive",
    "description": (
        "Create one native Part primitive solid (box, cylinder, sphere, cone, or "
        "torus) at an exact position. Primitives are standalone parametric objects; "
        "combine them with part.boolean and reposition them with part.set_placement."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "primitive": {
                "description": "Primitive shape to create; choose exactly one variant.",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "box",
                                "description": "Rectangular box.",
                            },
                            "length_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Box size along X in mm.",
                            },
                            "width_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Box size along Y in mm.",
                            },
                            "height_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Box size along Z in mm.",
                            },
                        },
                        "required": ["type", "length_mm", "width_mm", "height_mm"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "cylinder",
                                "description": "Cylinder along the local Z axis.",
                            },
                            "radius_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Cylinder radius in mm.",
                            },
                            "height_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Cylinder height along Z in mm.",
                            },
                            "angle_degrees": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "maximum": 360,
                                "description": (
                                    "Sweep angle in degrees; 360 for a full cylinder."
                                ),
                            },
                        },
                        "required": ["type", "radius_mm", "height_mm", "angle_degrees"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "sphere",
                                "description": "Full sphere.",
                            },
                            "radius_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Sphere radius in mm.",
                            },
                        },
                        "required": ["type", "radius_mm"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "cone",
                                "description": "Cone or truncated cone along the local Z axis.",
                            },
                            "bottom_radius_mm": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Radius at the base in mm; 0 for a sharp apex at "
                                    "the bottom."
                                ),
                            },
                            "top_radius_mm": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Radius at the top in mm; 0 for a sharp apex at "
                                    "the top."
                                ),
                            },
                            "height_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Cone height along Z in mm.",
                            },
                        },
                        "required": [
                            "type",
                            "bottom_radius_mm",
                            "top_radius_mm",
                            "height_mm",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "torus",
                                "description": "Full torus around the local Z axis.",
                            },
                            "ring_radius_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Distance from the torus center to the tube "
                                    "center in mm; must exceed tube_radius_mm."
                                ),
                            },
                            "tube_radius_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Radius of the circular tube in mm.",
                            },
                        },
                        "required": ["type", "ring_radius_mm", "tube_radius_mm"],
                        "additionalProperties": False,
                    },
                ],
            },
            "position": domain_runtime.vector_schema(
                "Global position of the primitive's local origin in mm."
            ),
            "label": {
                "type": "string",
                "description": "Visible label for the new object, e.g. 'BasePlate'.",
            },
        },
        "required": ["primitive", "position", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    primitive: dict[str, Any],
    position: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(primitive, dict):
        return _invalid("primitive must be an object.")
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    kind = str(primitive.get("type") or "")
    build = _BUILDERS.get(kind)
    if build is None:
        return _invalid("primitive.type must be box, cylinder, sphere, cone, or torus.")
    if kind == "cone":
        if (
            float(primitive.get("bottom_radius_mm") or 0.0) <= 0.0
            and float(primitive.get("top_radius_mm") or 0.0) <= 0.0
        ):
            return _invalid("A cone needs at least one non-zero radius.")
    if kind == "torus":
        if float(primitive["tube_radius_mm"]) >= float(primitive["ring_radius_mm"]):
            return _invalid(
                "torus tube_radius_mm must be smaller than ring_radius_mm; "
                "equal or larger values self-intersect."
            )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        obj = build(doc, primitive)
        obj.Label = clean_label
        obj.Placement = App.Placement(
            domain_runtime.parse_vector(position), App.Rotation()
        )
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": obj.Name,
            "feature_label": obj.Label,
            "feature_type": obj.TypeId,
            "primitive_type": kind,
            "placement_position": {
                "x": float(obj.Placement.Base.x),
                "y": float(obj.Placement.Base.y),
                "z": float(obj.Placement.Base.z),
            },
            "shape": domain_runtime.shape_summary(obj),
            "feature_state": domain_runtime.feature_state_summary(obj),
        }

    transaction = run_freecad_transaction(
        f"Create Part {kind}: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation=f"create_{kind}")


def _build_box(doc: Any, spec: dict[str, Any]) -> Any:
    obj = doc.addObject("Part::Box", "Box")
    obj.Length = float(spec["length_mm"])
    obj.Width = float(spec["width_mm"])
    obj.Height = float(spec["height_mm"])
    return obj


def _build_cylinder(doc: Any, spec: dict[str, Any]) -> Any:
    obj = doc.addObject("Part::Cylinder", "Cylinder")
    obj.Radius = float(spec["radius_mm"])
    obj.Height = float(spec["height_mm"])
    obj.Angle = float(spec["angle_degrees"])
    return obj


def _build_sphere(doc: Any, spec: dict[str, Any]) -> Any:
    obj = doc.addObject("Part::Sphere", "Sphere")
    obj.Radius = float(spec["radius_mm"])
    return obj


def _build_cone(doc: Any, spec: dict[str, Any]) -> Any:
    obj = doc.addObject("Part::Cone", "Cone")
    obj.Radius1 = float(spec["bottom_radius_mm"])
    obj.Radius2 = float(spec["top_radius_mm"])
    obj.Height = float(spec["height_mm"])
    return obj


def _build_torus(doc: Any, spec: dict[str, Any]) -> Any:
    obj = doc.addObject("Part::Torus", "Torus")
    obj.Radius1 = float(spec["ring_radius_mm"])
    obj.Radius2 = float(spec["tube_radius_mm"])
    return obj


_BUILDERS = {
    "box": _build_box,
    "cylinder": _build_cylinder,
    "sphere": _build_sphere,
    "cone": _build_cone,
    "torus": _build_torus,
}


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
