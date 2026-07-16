# SPDX-License-Identifier: LGPL-2.1-or-later

"""Apply exact source replacements to one persisted VibeScript model."""

from __future__ import annotations


TOOL_SPEC = {
    "name": "vibescript.edit_source",
    "description": (
        "Surgically edit one existing VibeScript program, optionally changing "
        "its driving parameters in the same atomic run. First inspect the "
        "model; consult vibescript.describe_api for the authoring helpers "
        "available in source. Each old_text "
        "block must match the inspected source exactly once at its edit step; "
        "otherwise nothing runs. When parameter_patch is supplied it is applied "
        "to the current flat params with RFC 7396 merge semantics (null removes "
        "a key), so source edits that add or retire parameters land together "
        "with the matching parameter changes in one prepared candidate. The "
        "candidate program is policy-checked and "
        "executed inside one document transaction, so a failed run leaves the "
        "accepted FreeCAD geometry untouched. Failed working revisions remain "
        "editable and do not replace the last accepted output."
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
            "edits": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "description": "Ordered exact source replacements applied to the inspected revision.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Exact current source block that must occur once.",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement block; empty deletes the exact match.",
                        },
                    },
                    "required": ["old_text", "new_text"],
                    "additionalProperties": False,
                },
            },
            "parameter_patch": {
                "type": "object",
                "minProperties": 1,
                "description": "Optional JSON merge patch applied to the current flat params object in the same atomic run as the source edits. Each key maps to a single finite number (set or replace that parameter) or null (remove it); nested objects, arrays, strings, and booleans are rejected. Every key must be a valid Python identifier not starting with an underscore.",
                "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]*$"},
                "additionalProperties": {"type": ["number", "null"]},
            },
        },
        "required": ["model_id", "expected_revision", "edits"],
        "additionalProperties": False,
    },
}


RUNNER_HANDLED = True
