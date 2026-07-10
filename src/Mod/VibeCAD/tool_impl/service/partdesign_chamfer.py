# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Chamfer tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_dressup_feature


_DEFINITION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "equal_distance"},
                "size": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["type", "size"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "two_distances"},
                "size": {"type": "number", "exclusiveMinimum": 0},
                "second_size": {"type": "number", "exclusiveMinimum": 0},
                "flip_direction": {"type": "boolean"},
            },
            "required": ["type", "size", "second_size", "flip_direction"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "distance_angle"},
                "size": {"type": "number", "exclusiveMinimum": 0},
                "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
                "flip_direction": {"type": "boolean"},
            },
            "required": ["type", "size", "angle_degrees", "flip_direction"],
            "additionalProperties": False,
        },
    ]
}

TOOL_SPEC = {
    "name": "partdesign.chamfer",
    "description": (
        "Create one native equal-distance, two-distance, or distance-angle PartDesign Chamfer "
        "on the current valid Body Tip with exact or count-guarded geometric selection."
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
            "selection": partdesign_dressup_feature.selection_schema(allow_all_edges=True),
            "definition": _DEFINITION_SCHEMA,
            "refine": {"type": "boolean"},
            "support_transform": {"type": "boolean"},
        },
        "required": [
            "base_feature_name", "label", "selection", "definition", "refine",
            "support_transform",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_dressup_feature.run(
        service,
        operation="chamfer",
        type_id="PartDesign::Chamfer",
        **arguments,
    )
