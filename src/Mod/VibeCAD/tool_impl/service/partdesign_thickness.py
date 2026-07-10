# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Thickness tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_dressup_feature


TOOL_SPEC = {
    "name": "partdesign.thickness",
    "description": (
        "Create one native PartDesign Thickness shell from exact or count-guarded opening faces "
        "on the current Body Tip with named direction, mode, join, and intersection behavior."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "base_feature_name": {"type": "string"},
            "label": {"type": "string"},
            "selection": partdesign_dressup_feature.selection_schema(
                allow_all_edges=False,
                face_only=True,
            ),
            "wall_thickness": {"type": "number", "exclusiveMinimum": 0},
            "direction": {"type": "string", "enum": ["inward", "outward"]},
            "mode": {"type": "string", "enum": ["skin", "pipe", "recto_verso"]},
            "join": {"type": "string", "enum": ["arc", "intersection"]},
            "intersection_handling": {"type": "boolean"},
            "refine": {"type": "boolean"},
            "support_transform": {"type": "boolean"},
        },
        "required": [
            "base_feature_name", "label", "selection", "wall_thickness", "direction",
            "mode", "join", "intersection_handling", "refine", "support_transform",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_dressup_feature.run(
        service,
        operation="thickness",
        type_id="PartDesign::Thickness",
        **arguments,
    )
