# SPDX-License-Identifier: LGPL-2.1-or-later

"""Change VibeScript driving parameters without rewriting source."""

from __future__ import annotations


TOOL_SPEC = {
    "name": "vibescript.set_parameters",
    "description": (
        "Update only the driving parameters of one inspected VibeScript model "
        "and rerun its unchanged source. patch uses RFC 7396 JSON merge "
        "semantics: objects merge recursively and null removes a key. The rerun "
        "executes inside one document transaction and is geometry-validated "
        "before accepted FreeCAD geometry changes; failed working parameters "
        "remain inspectable and repairable."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$",
                "description": "Exact model id returned by vibescript.inspect_model.",
            },
            "expected_revision": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
                "description": "Exact current revision returned by vibescript.inspect_model.",
            },
            "patch": {
                "type": "object",
                "minProperties": 1,
                "description": "JSON merge patch applied to the current flat params object. Each key maps to a single finite number (set or replace that parameter) or null (remove it); nested objects, arrays, strings, and booleans are rejected. Every key must be a valid Python identifier not starting with an underscore.",
                "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]*$"},
                "additionalProperties": {"type": ["number", "null"]},
            },
        },
        "required": ["model_id", "expected_revision", "patch"],
        "additionalProperties": False,
    },
}


RUNNER_HANDLED = True
