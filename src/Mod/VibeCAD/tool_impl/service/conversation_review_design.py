# SPDX-License-Identifier: LGPL-2.1-or-later

"""Independent, read-only review of a written mechanical design draft."""

from __future__ import annotations


TOOL_SPEC = {
    "name": "conversation.review_design",
    "description": (
        "Submit a complete written proposal for an independent adversarial "
        "mechanical-design review before the first CAD write of a substantial "
        "new design. The reviewer has no CAD mutation tools. Use its structured "
        "findings to repair the proposal before construction; do not use this "
        "for routine edits or as a user approval gate."
    ),
    "safety": "READ",
    "requires_document": False,
    "parameters": {
        "type": "object",
        "properties": {
            "customer_intent": {
                "type": "string",
                "minLength": 20,
                "description": (
                    "Faithful restatement of the requested outcome and explicit "
                    "requirements, without replacing them with easier geometry."
                ),
            },
            "design_draft": {
                "type": "string",
                "minLength": 80,
                "description": (
                    "Concrete proposed architecture covering components, primary "
                    "geometry, interfaces, mechanisms, load and motion paths, "
                    "fits, materials, manufacturing, tolerances, verification, "
                    "assumptions, and known risks."
                ),
            },
        },
        "required": ["customer_intent", "design_draft"],
        "additionalProperties": False,
    },
}


RUNNER_HANDLED = True
