# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Fillet tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_dressup_feature


TOOL_SPEC = {
    "name": "partdesign.fillet",
    "description": (
        "Create one native PartDesign Fillet on the current valid Body Tip. Select exact "
        "edges/faces, all edges, or a geometric query with a required match count."
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
            "definition": {
                "type": "object",
                "properties": {"radius": {"type": "number", "exclusiveMinimum": 0}},
                "required": ["radius"],
                "additionalProperties": False,
            },
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
        operation="fillet",
        type_id="PartDesign::Fillet",
        **arguments,
    )
