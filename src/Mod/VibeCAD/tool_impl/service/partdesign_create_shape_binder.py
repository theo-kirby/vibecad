# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign ShapeBinder tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_reference_feature


TOOL_SPEC = {
    "name": "partdesign.create_shape_binder",
    "description": (
        "Create one native ShapeBinder inside an exact Body from exact whole-object or "
        "subelement references, preserving live support links and optional support tracing."
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
            "trace_support": {"type": "boolean"},
        },
        "required": ["body_name", "label", "references", "trace_support"],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_reference_feature.run(
        service,
        operation="shape_binder",
        type_id="PartDesign::ShapeBinder",
        **arguments,
    )
