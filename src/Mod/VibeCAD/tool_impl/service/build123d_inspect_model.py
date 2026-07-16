# SPDX-License-Identifier: LGPL-2.1-or-later

"""Read one persisted build123d model definition and its output mapping."""

from __future__ import annotations

from typing import Any

from VibeCADBuild123d import inspect_model


TOOL_SPEC = {
    "name": "build123d.inspect_model",
    "description": (
        "Read one build123d model's complete working source, parameters, inputs, "
        "outputs, working/accepted revisions, accepted FreeCAD geometry facts, and "
        "latest failed-attempt evidence. Use the returned working revision as the "
        "base of an edit; repair failed candidates instead of recreating them."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$",
                "description": "Exact model id from the live build123d model summary.",
            }
        },
        "required": ["model_id"],
        "additionalProperties": False,
    },
}


def run(service: Any, model_id: str) -> dict[str, Any]:
    return inspect_model(service, model_id)
