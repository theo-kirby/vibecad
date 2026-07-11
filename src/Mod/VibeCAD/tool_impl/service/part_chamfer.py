# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Part chamfer on exact named edges."""

from __future__ import annotations

from typing import Any

from . import part_fillet


TOOL_SPEC = {
    "name": "part.chamfer",
    "description": (
        "Create one native Part chamfer that bevels exact named edges of one shaped "
        "object with an equal-distance cut. Finishing operation; apply after the "
        "primary form is complete. Resolve edge names with part.find_subelements "
        "first - never guess them. The source object becomes a hidden child of the "
        "chamfer result."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Exact internal name of the object whose edges are chamfered.",
            },
            "edge_names": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Exact edge names such as Edge3, from part.find_subelements.",
            },
            "size_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Chamfer distance in mm measured from the edge along both "
                    "adjacent faces."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the chamfer result.",
            },
        },
        "required": ["object_name", "edge_names", "size_mm", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    object_name: str,
    edge_names: list[str],
    size_mm: float,
    label: str,
) -> dict[str, Any]:
    return part_fillet.run_edge_finish(
        service,
        object_name=object_name,
        edge_names=edge_names,
        size_mm=size_mm,
        label=label,
        native_type="Part::Chamfer",
        operation="chamfer",
    )
