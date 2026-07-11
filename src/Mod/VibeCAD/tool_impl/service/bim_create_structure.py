# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native BIM structural element (column, beam, or slab)."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "bim.create_structure",
    "description": (
        "Create one native BIM structural element: a vertical column, a "
        "horizontal beam, or a slab. Columns and beams are rectangular boxes "
        "placed at an exact position (the corner with the smallest X/Y/Z). "
        "Slabs extrude an exact closed planar profile object downward by "
        "their thickness, so draw the profile with make_face=true at the "
        "level's floor elevation first. Each element is classified with the "
        "matching IFC type."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "BIMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "element": {
                "description": (
                    "Structural element to create; choose exactly one variant."
                ),
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "column",
                                "description": "Vertical column extruded along Z.",
                            },
                            "width_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Column cross-section size along X in mm."
                                ),
                            },
                            "depth_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Column cross-section size along Y in mm."
                                ),
                            },
                            "height_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Column height along Z in mm.",
                            },
                            "position": domain_runtime.vector_schema(
                                "Global position of the column's minimum-X/Y/Z "
                                "corner in mm."
                            ),
                        },
                        "required": [
                            "type",
                            "width_mm",
                            "depth_mm",
                            "height_mm",
                            "position",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "beam",
                                "description": (
                                    "Horizontal beam spanning along the X axis."
                                ),
                            },
                            "span_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Beam span along X in mm.",
                            },
                            "width_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Beam cross-section size along Y in mm."
                                ),
                            },
                            "depth_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Beam cross-section size along Z (vertical "
                                    "depth) in mm."
                                ),
                            },
                            "position": domain_runtime.vector_schema(
                                "Global position of the beam's minimum-X/Y/Z "
                                "corner in mm; Z is the beam's underside."
                            ),
                        },
                        "required": [
                            "type",
                            "span_mm",
                            "width_mm",
                            "depth_mm",
                            "position",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "slab",
                                "description": (
                                    "Floor/ceiling slab extruded downward from "
                                    "an exact planar profile."
                                ),
                            },
                            "profile_object": {
                                "type": "string",
                                "description": (
                                    "Exact internal name of the closed planar "
                                    "profile object (from "
                                    "draft.create_rectangle or "
                                    "draft.create_wire with make_face=true) "
                                    "outlining the slab; the profile is "
                                    "consumed and hidden."
                                ),
                            },
                            "thickness_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Slab thickness in mm, extruded downward "
                                    "so the slab top sits at the profile "
                                    "plane."
                                ),
                            },
                        },
                        "required": ["type", "profile_object", "thickness_mm"],
                        "additionalProperties": False,
                    },
                ],
            },
            "level_object": {
                "type": "string",
                "description": (
                    "Exact internal name of the level (building storey from "
                    "bim.create_spatial_structure) to file this element "
                    "under; empty string to leave it outside the spatial "
                    "structure."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Visible label for the new element, e.g. 'CornerColumn'."
                ),
            },
        },
        "required": ["element", "level_object", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    element: dict[str, Any],
    level_object: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(element, dict):
        return _invalid("element must be an object.")
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    kind = str(element.get("type") or "")
    if kind == "column":
        dims = ("width_mm", "depth_mm", "height_mm")
    elif kind == "beam":
        dims = ("span_mm", "width_mm", "depth_mm")
    elif kind == "slab":
        dims = ("thickness_mm",)
    else:
        return _invalid("element.type must be column, beam, or slab.")
    values: dict[str, float] = {}
    for dim in dims:
        value = float(element.get(dim) or 0.0)
        if value <= 0:
            return _invalid(f"element.{dim} must be greater than 0.")
        values[dim] = value
    profile_name = str(element.get("profile_object") or "").strip()
    if kind == "slab" and not profile_name:
        return _invalid("element.profile_object is required for a slab.")
    position = element.get("position")
    if kind in ("column", "beam") and not isinstance(position, dict):
        return _invalid(f"element.position is required for a {kind}.")
    level_name = str(level_object or "").strip()

    def create() -> dict[str, Any]:
        import Arch
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        level = None
        if level_name:
            level = doc.getObject(level_name)
            if level is None:
                raise RuntimeError(
                    f"Level object '{level_name}' not found; use "
                    "bim.list_structure for exact names."
                )
        profile = None
        if kind == "column":
            obj = Arch.makeStructure(
                length=values["width_mm"],
                width=values["depth_mm"],
                height=values["height_mm"],
                name=clean_label,
            )
        elif kind == "beam":
            obj = Arch.makeStructure(
                length=values["span_mm"],
                width=values["width_mm"],
                height=values["depth_mm"],
                name=clean_label,
            )
        else:
            profile = doc.getObject(profile_name)
            if profile is None:
                raise RuntimeError(
                    f"Profile object '{profile_name}' not found; use "
                    "draft.list_objects for exact names."
                )
            profile_shape = getattr(profile, "Shape", None)
            if profile_shape is None or not getattr(profile_shape, "Faces", []):
                raise RuntimeError(
                    f"Profile object '{profile_name}' has no planar face; "
                    "create it closed with make_face=true so the slab has an "
                    "outline to extrude."
                )
            obj = Arch.makeStructure(
                profile,
                height=values["thickness_mm"],
                name=clean_label,
            )
        if obj is None:
            raise RuntimeError("Arch.makeStructure did not create an object.")
        if kind == "slab":
            obj.IfcType = "Slab"
            obj.Normal = App.Vector(0, 0, -1)
        else:
            obj.Placement = App.Placement(
                domain_runtime.parse_vector(position), App.Rotation()
            )
        obj.Label = clean_label
        if level is not None:
            level.addObject(obj)
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": obj.Name,
            "feature_label": obj.Label,
            "feature_type": obj.TypeId,
            "ifc_type": getattr(obj, "IfcType", None),
            "element_type": kind,
            "profile_object": profile.Name if profile is not None else None,
            "level_object": level.Name if level is not None else None,
            "shape": domain_runtime.shape_summary(obj),
            "feature_state": domain_runtime.feature_state_summary(obj),
        }

    transaction = run_freecad_transaction(
        f"Create BIM {kind}: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction,
        operation=f"create_{kind}",
        next_action=(
            "Verify the element position with part.measure or a screenshot, "
            "then continue placing elements."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
