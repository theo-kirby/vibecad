# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.enter_workspace``."""

from __future__ import annotations


TOOL_SPEC = {
    "description": (
        "Switch to a FreeCAD workspace/workbench. This is the only "
        "workspace-switching tool: entering a workspace exposes its full "
        "CAD tool pack on the next turn. Call it before using any "
        "workspace-specific tool."
    ),
    "name": "core.enter_workspace",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Workbench name such as PartDesignWorkbench or SketcherWorkbench.",
            },
            "goal": {
                "type": "string",
                "description": "Short model-written goal for this workspace session.",
            },
            "reason": {
                "type": "string",
                "description": "Why this workspace is the right place for the next operation.",
            },
        },
        "required": ["name"],
    },
    "safety": "VIEW",
}


def run(service, name: str, goal: str = "", reason: str = "") -> dict[str, object]:
    from tool_impl.service.core_activate_workbench import run as activate_workbench
    from VibeCADWorkbenchTools import get_tool_pack

    result = activate_workbench(service, name=name)
    active = result.get("active")
    if active is None:
        active = result.get("active_workbench")
    known_workspace = get_tool_pack(name) is not None
    ok = bool(result.get("activated")) or active == name or known_workspace
    response: dict[str, object] = {
        "ok": ok,
        "requested": name,
        "active_workbench": active or name,
        "workspace": active or name,
        "goal": str(goal or "").strip(),
        "reason": str(reason or "").strip(),
        "workspace_session": {
            "workbench": active or name,
            "goal": str(goal or "").strip(),
            "reason": str(reason or "").strip(),
        },
    }
    if result.get("error"):
        if ok:
            response["activation_warning"] = result["error"]
        else:
            response["error"] = result["error"]
            response["recoverable"] = True
    return response
