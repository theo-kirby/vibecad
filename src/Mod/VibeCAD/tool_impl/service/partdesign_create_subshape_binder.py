# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign SubShapeBinder tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_reference_feature


TOOL_SPEC = {
    "name": "partdesign.create_subshape_binder",
    "description": (
        "Create one native SubShapeBinder inside an exact Body from exact multi-object geometry "
        "references with named bind, offset, face-building, fuse, and update behavior."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "body_name": {"type": "string"},
            "label": {"type": "string"},
            "references": {
                "type": "array",
                "items": partdesign_reference_feature.REFERENCE_SCHEMA,
                "minItems": 1,
            },
            "fuse": {"type": "boolean"},
            "make_face": {"type": "boolean"},
            "offset": {"type": "number"},
            "offset_join": {
                "type": "string",
                "enum": ["arcs", "tangent", "intersection"],
            },
            "offset_fill": {"type": "boolean"},
            "offset_open_result": {"type": "boolean"},
            "offset_intersection": {"type": "boolean"},
            "relative": {"type": "boolean"},
            "bind_mode": {
                "type": "string",
                "enum": ["synchronized", "frozen", "detached"],
            },
            "partial_load": {"type": "boolean"},
            "copy_on_change": {
                "type": "string",
                "enum": ["disabled", "enabled", "mutated"],
            },
            "refine": {"type": "boolean"},
        },
        "required": [
            "body_name", "label", "references", "fuse", "make_face", "offset",
            "offset_join", "offset_fill", "offset_open_result", "offset_intersection",
            "relative", "bind_mode", "partial_load", "copy_on_change", "refine",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_reference_feature.run(
        service,
        operation="subshape_binder",
        type_id="PartDesign::SubShapeBinder",
        **arguments,
    )
