# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign MultiTransform tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_transform_feature


_TRANSFORMATION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "linear"},
                "reference": partdesign_transform_feature.AXIS_REFERENCE_SCHEMA,
                "distribution": partdesign_transform_feature.distribution_schema("length"),
                "reversed": {"type": "boolean"},
            },
            "required": ["type", "reference", "distribution", "reversed"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "polar"},
                "reference": partdesign_transform_feature.AXIS_REFERENCE_SCHEMA,
                "distribution": partdesign_transform_feature.distribution_schema("angle_degrees", 360.0),
                "reversed": {"type": "boolean"},
            },
            "required": ["type", "reference", "distribution", "reversed"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "mirror"},
                "reference": partdesign_transform_feature.PLANE_REFERENCE_SCHEMA,
            },
            "required": ["type", "reference"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "scale"},
                "factor": {"type": "number", "exclusiveMinimum": 0},
                "occurrences": {"type": "integer", "minimum": 2},
            },
            "required": ["type", "factor", "occurrences"],
            "additionalProperties": False,
        },
    ]
}

TOOL_SPEC = {
    "name": "partdesign.multi_transform",
    "description": (
        "Create one native MultiTransform from one or more exact source features and an ordered "
        "composition of at least two mirror, linear, polar, or scale transformations."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "feature_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "label": {"type": "string"},
            "transformations": {
                "type": "array",
                "items": _TRANSFORMATION_SCHEMA,
                "minItems": 2,
            },
            "transform_mode": partdesign_transform_feature.TRANSFORM_MODE_SCHEMA,
            "refine": {"type": "boolean"},
        },
        "required": ["feature_names", "label", "transformations", "transform_mode", "refine"],
        "additionalProperties": False,
    },
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_transform_feature.run_multi_transform(service, **arguments)
