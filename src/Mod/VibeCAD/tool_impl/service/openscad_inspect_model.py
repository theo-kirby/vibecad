# SPDX-License-Identifier: LGPL-2.1-or-later

"""Inspect one persisted OpenSCAD model."""

from __future__ import annotations

from typing import Any

from VibeCADOpenSCAD import inspect_model


TOOL_SPEC = {
    "name": "openscad.inspect_model",
    "description": (
        "Read one OpenSCAD model's complete working source, parameters, working and "
        "accepted revisions, generated solids, geometry fidelity, and latest failed "
        "attempt diagnostics. Inspect before editing and use the returned working "
        "revision as the edit base."
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
                "description": "Exact model id from the live OpenSCAD model summary.",
            }
        },
        "required": ["model_id"],
        "additionalProperties": False,
    },
}


def run(service: Any, model_id: str) -> dict[str, Any]:
    return inspect_model(service, model_id)
