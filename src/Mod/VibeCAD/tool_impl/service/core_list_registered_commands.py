# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_registered_commands``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Read-only diagnostic: return registered FreeCAD GUI '
                'command names. GUI commands are not provider tools; prefer '
                'core.list_active_workbench_commands when inspecting a workbench pack.',
 'name': 'core.list_registered_commands',
 'safety': 'READ'}


def run(service, **kwargs):
    try:
        import FreeCADGui as Gui

        commands = sorted(Gui.listCommands())
        visible, bounds = _bounded_items(commands, 120)
        return {
            "command_count": len(commands),
            "command_limit": bounds["limit"],
            "commands_truncated": bounds["truncated"],
            "commands_omitted": bounds["omitted"],
            "commands": visible,
        }
    except Exception as exc:
        return {"command_count": 0, "commands": [], "error": str(exc)}


def _bounded_items(items, limit):
    safe_limit = max(0, int(limit))
    visible = list(items[:safe_limit])
    omitted = max(0, len(items) - len(visible))
    return visible, {
        "limit": safe_limit,
        "truncated": omitted > 0,
        "omitted": omitted,
    }
