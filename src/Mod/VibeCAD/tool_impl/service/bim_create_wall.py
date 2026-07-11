# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native BIM wall from an exact baseline object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "bim.create_wall",
    "description": (
        "Create one native BIM wall by extruding an exact baseline object "
        "(a Draft wire or line from draft.create_wire) upward. The wall "
        "follows the baseline path with the given height and thickness; the "
        "baseline object is consumed as the wall's base and hidden. Draw the "
        "baseline at the level's floor elevation first."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "BIMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "baseline_object": {
                "type": "string",
                "description": (
                    "Exact internal name of the baseline object (e.g. a Draft "
                    "wire 'Wire' from draft.list_objects) the wall follows."
                ),
            },
            "height_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Wall height above the baseline in mm.",
            },
            "thickness_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Wall thickness in mm.",
            },
            "alignment": {
                "type": "string",
                "enum": ["center", "left", "right"],
                "description": (
                    "Which side of the baseline the wall thickness grows "
                    "toward: 'center' splits it evenly, 'left'/'right' place "
                    "the full thickness on that side of the baseline "
                    "direction."
                ),
            },
            "level_object": {
                "type": "string",
                "description": (
                    "Exact internal name of the level (building storey from "
                    "bim.create_spatial_structure) to file this wall under; "
                    "empty string to leave the wall outside the spatial "
                    "structure."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new wall, e.g. 'NorthWall'.",
            },
        },
        "required": [
            "baseline_object",
            "height_mm",
            "thickness_mm",
            "alignment",
            "level_object",
            "label",
        ],
        "additionalProperties": False,
    },
}

_ALIGNMENTS = {"center": "Center", "left": "Left", "right": "Right"}


def run(
    service: Any,
    baseline_object: str,
    height_mm: float,
    thickness_mm: float,
    alignment: str,
    level_object: str,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    baseline_name = str(baseline_object or "").strip()
    if not baseline_name:
        return _invalid("baseline_object is required.")
    height = float(height_mm)
    thickness = float(thickness_mm)
    if height <= 0:
        return _invalid("height_mm must be greater than 0.")
    if thickness <= 0:
        return _invalid("thickness_mm must be greater than 0.")
    align = _ALIGNMENTS.get(str(alignment or ""))
    if align is None:
        return _invalid("alignment must be center, left, or right.")
    level_name = str(level_object or "").strip()

    def create() -> dict[str, Any]:
        import Arch
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        baseline = doc.getObject(baseline_name)
        if baseline is None:
            raise RuntimeError(
                f"Baseline object '{baseline_name}' not found; use "
                "draft.list_objects for exact names."
            )
        shape = getattr(baseline, "Shape", None)
        if shape is None or not getattr(shape, "Edges", []):
            raise RuntimeError(
                f"Baseline object '{baseline_name}' has no edges to follow; "
                "create it with draft.create_wire first."
            )
        level = None
        if level_name:
            level = doc.getObject(level_name)
            if level is None:
                raise RuntimeError(
                    f"Level object '{level_name}' not found; use "
                    "bim.list_structure for exact names."
                )
        wall = Arch.makeWall(
            baseline,
            height=height,
            width=thickness,
            align=align,
            name=clean_label,
        )
        if wall is None:
            raise RuntimeError("Arch.makeWall did not create an object.")
        if level is not None:
            level.addObject(wall)
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": wall.Name,
            "feature_label": wall.Label,
            "feature_type": wall.TypeId,
            "ifc_type": getattr(wall, "IfcType", None),
            "baseline_object": baseline.Name,
            "level_object": level.Name if level is not None else None,
            "shape": domain_runtime.shape_summary(wall),
            "feature_state": domain_runtime.feature_state_summary(wall),
        }

    transaction = run_freecad_transaction(
        f"Create BIM wall: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction,
        operation="create_wall",
        next_action=(
            "Add openings with bim.add_window, or create the next wall; "
            "capture a screenshot to verify placement."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
