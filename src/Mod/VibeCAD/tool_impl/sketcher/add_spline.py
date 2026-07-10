# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create a native Sketcher B-spline."""

from __future__ import annotations

from typing import Any

from . import add_geometry


TOOL_SPEC = {
    "name": "sketcher.add_spline",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Add a native B-spline from ordered sketch-local points. Use for "
        "airfoils, ergonomic contours, blade profiles, ducts, and other smooth "
        "form that cannot be represented honestly by straight segments or one arc."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "minItems": 3,
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "interpolate": {
                "type": "boolean",
                "description": "True passes through the points; false treats them as control poles.",
            },
            "periodic": {
                "type": "boolean",
                "description": (
                    "True creates a native periodic closed spline and requires at least five "
                    "distinct points without repeating the first point at the end."
                ),
            },
            "construction": {"type": "boolean"},
        },
        "required": [
            "points",
            "interpolate",
            "periodic",
            "construction",
        ],
        "additionalProperties": False,
    },
}


def run(service: Any, **kwargs: Any) -> dict[str, Any]:
    return add_geometry.run(service, kind="bspline", **kwargs)
