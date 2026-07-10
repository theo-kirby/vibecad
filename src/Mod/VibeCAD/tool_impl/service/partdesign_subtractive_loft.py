# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign Subtractive Loft tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_loft_feature


TOOL_SPEC = {
    "name": "partdesign.subtractive_loft",
    "description": (
        "Create one native subtractive loft through two or more ordered, closed sketches already "
        "owned by the same solid Body. Use for varying passages, ports, cooling channels, and "
        "non-prismatic material removal."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "profile_names": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
            "label": {"type": "string"},
            "closed": {"type": "boolean"},
            "ruled": {"type": "boolean"},
            "reversed": {"type": "boolean"},
            "midplane": {"type": "boolean"},
            "refine": {"type": "boolean"},
        },
        "required": [
            "profile_names",
            "label",
            "closed",
            "ruled",
            "reversed",
            "midplane",
            "refine",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_loft_feature.run(
        service,
        operation="subtractive_loft",
        type_id="PartDesign::SubtractiveLoft",
        **arguments,
    )
