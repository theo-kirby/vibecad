# SPDX-License-Identifier: LGPL-2.1-or-later

"""List the CSG structure of an imported OpenSCAD model with exact names."""

from __future__ import annotations

from typing import Any

from . import domain_runtime


TOOL_SPEC = {
    "name": "openscad.list_csg",
    "description": (
        "List every object in the active document with its CSG structure: "
        "exact internal name, proxy type, child object links, and shape or "
        "mesh counts. Use this to understand an imported OpenSCAD model's "
        "boolean tree before deciding what to edit; OpenSCAD import and "
        "script execution run in the FreeCAD GUI."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "OpenSCADWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def run(service: Any) -> dict[str, Any]:
    try:
        summary = domain_runtime.openscad_summary(service)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not list CSG objects: {exc}",
            "retry_same_call": False,
        }
    return {"ok": True, **summary}
