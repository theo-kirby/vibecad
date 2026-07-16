# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one persisted VibeScript model from complete initial source."""

from __future__ import annotations


TOOL_SPEC = {
    "name": "vibescript.create_model",
    "description": (
        "Create one new persisted VibeScript model whose named outputs are native "
        "parametric PartDesign feature trees, editable in the FreeCAD GUI "
        "afterward. Call vibescript.describe_api once before writing the first "
        "source to learn every available helper, the execution namespace, the "
        "import policy, and the budget. Source executes in-process against the "
        "live document inside "
        "one transaction, uses millimetres, receives doc and params, and must "
        "assign result to an ordered dict whose keys exactly match "
        "expected_outputs and whose values are document objects each owning "
        "exactly one valid solid. Use one model for one independently editable "
        "component or coherent subassembly; do not put an entire complex product "
        "in one program. A failed candidate is persisted under its returned "
        "model id so it can be inspected and repaired without recreating the "
        "program."
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
                "description": "Complete initial VibeScript Python source assigning the final output dictionary to result. Build every sketch with SketchBuilder so it is fully constrained through named dimensions instead of raw constraint index tuples. Select dress-up edges with EdgeQuery geometric predicates immediately from the feature that creates them and keep them in named variables instead of rediscovering final-shape edge indices. Drive dimensions from params so the algebra persists as live expressions in the document. Imports are limited to FreeCAD, Part, PartDesign, Sketcher, vibescript_api, and safe stdlib modules.",
            },
            "parameters": {
                "type": "object",
                "description": "Flat object of driving dimensions exposed to source as params. Every value must be a single finite number (millimetres or degrees); nested objects, arrays, strings, and booleans are rejected. Compute derived tables or interpolated values inside source from these scalars. Every key must be a valid Python identifier not starting with an underscore.",
                "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]*$"},
                "additionalProperties": {"type": "number"},
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
        "required": ["model_name", "source", "parameters", "expected_outputs"],
        "additionalProperties": False,
    },
}


RUNNER_HANDLED = True
