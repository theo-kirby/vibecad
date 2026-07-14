# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one persisted build123d model from complete initial source."""

from __future__ import annotations


TOOL_SPEC = {
    "name": "build123d.create_model",
    "description": (
        "Create one new persisted build123d model and its named physical outputs. "
        "Source runs in the isolated build123d 0.11.1 sidecar, uses millimetres, "
        "receives params and inputs, and must assign result to an ordered dict whose "
        "keys exactly match expected_outputs and whose values are valid single-solid "
        "build123d Shapes. Use one model for one independently editable component or "
        "coherent subassembly; do not put an entire complex product in one program. "
        "A failed candidate is persisted under its returned model id so it can be "
        "inspected and repaired without recreating the program."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "model_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "description": "Unique human-readable label for this component model.",
            },
            "source": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512000,
                "description": "Complete initial build123d Python source assigning the final Shape dictionary to result. Make alignment and placement explicit; assert critical datums, dimensions, and selector counts. For a curved or twisted loft, use enough intermediate sections to control its path because a two-section loft connects stations directly. Select dress-up edges immediately from the feature that creates them and keep them in named variables instead of rediscovering final-shape edge indices. Model required root flare or edge transitions into the primary geometry when dress-up clearance is marginal.",
            },
            "parameters": {
                "type": "object",
                "description": "Complete JSON-safe driving dimensions and configuration exposed to source as params.",
                "additionalProperties": True,
            },
            "input_objects": {
                "type": "object",
                "description": "Map of source aliases to exact shaped FreeCAD object names imported as inputs.",
                "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$"},
                "additionalProperties": {"type": "string", "minLength": 1},
            },
            "expected_outputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "uniqueItems": True,
                "description": "Ordered names of every physical single-solid output returned in result.",
                "items": {"type": "string", "minLength": 1, "maxLength": 96},
            },
        },
        "required": ["model_name", "source", "parameters", "input_objects", "expected_outputs"],
        "additionalProperties": False,
    },
}


RUNNER_HANDLED = True
