# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Pad tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_linear_feature


TOOL_SPEC = {
    "name": "partdesign.pad",
    "description": (
        "Create one native PartDesign Pad from an exact closed sketch in its owning Body. "
        "Supports dimensional, up-to-last, up-to-first, up-to-face, and up-to-shape extents, "
        "one/two/symmetric sides, taper, reversal, custom direction, and refine."
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
            "extent": partdesign_linear_feature.extent_schema(
                ["length", "up_to_last", "up_to_first", "up_to_face", "up_to_shape"]
            ),
            "side": {
                "type": "string",
                "enum": ["one_side", "two_sides", "symmetric"],
            },
            "reversed": {"type": "boolean"},
            "taper_angle_degrees": {"type": "number"},
            "second_taper_angle_degrees": {"type": "number"},
            "direction": partdesign_linear_feature.VECTOR_SCHEMA,
            "refine": {"type": "boolean"},
        },
        "required": [
            "profile_name",
            "label",
            "extent",
            "side",
            "reversed",
            "taper_angle_degrees",
            "second_taper_angle_degrees",
            "refine",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_linear_feature.run(
        service,
        operation="pad",
        type_id="PartDesign::Pad",
        **arguments,
    )
