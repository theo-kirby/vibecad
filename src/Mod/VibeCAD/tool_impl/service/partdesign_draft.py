# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Draft tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_dressup_feature, partdesign_transform_feature


TOOL_SPEC = {
    "name": "partdesign.draft",
    "description": (
        "Create one native PartDesign Draft on exact or count-guarded faces of the current Body "
        "Tip using an explicit neutral plane and pull direction; no direction is guessed."
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
            "neutral_plane": partdesign_transform_feature.PLANE_REFERENCE_SCHEMA,
            "pull_direction": partdesign_dressup_feature.DRAFT_PULL_DIRECTION_SCHEMA,
            "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 90},
            "reversed": {"type": "boolean"},
            "refine": {"type": "boolean"},
            "support_transform": {"type": "boolean"},
        },
        "required": [
            "base_feature_name", "label", "selection", "neutral_plane", "pull_direction",
            "angle_degrees", "reversed", "refine", "support_transform",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_dressup_feature.run(
        service,
        operation="draft",
        type_id="PartDesign::Draft",
        **arguments,
    )
