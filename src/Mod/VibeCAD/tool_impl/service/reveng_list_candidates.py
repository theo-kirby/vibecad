# SPDX-License-Identifier: LGPL-2.1-or-later

"""List reverse-engineering inputs and reconstructed outputs."""

from __future__ import annotations

from typing import Any

from . import domain_runtime


TOOL_SPEC = {
    "name": "reveng.list_candidates",
    "description": (
        "List reverse-engineering inputs (point clouds and meshes) and "
        "reconstructed outputs (fitted surfaces and splines) in the active "
        "document with exact internal names and geometry counts. Surface "
        "fitting itself runs in the FreeCAD GUI; use this to see what source "
        "data exists and what has already been reconstructed."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "ReverseEngineeringWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def run(service: Any) -> dict[str, Any]:
    try:
        summary = domain_runtime.reverseengineering_summary(service)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not list reverse-engineering objects: {exc}",
            "retry_same_call": False,
        }
    return {"ok": True, **summary}
