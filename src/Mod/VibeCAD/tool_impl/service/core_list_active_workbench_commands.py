# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_active_workbench_commands``."""

from __future__ import annotations

from VibeCADWorkbenchTools import get_tool_pack


TOOL_SPEC = {'contextual': True,
 'description': 'Return registered GUI commands for a workbench tool pack; run one '
                'with core.run_workbench_command when no structured tool exists.',
 'name': 'core.list_active_workbench_commands',
 'parameters': {'properties': {'workbench': {'description': 'Optional workbench name. '
                                                            'Defaults to the active '
                                                            'workbench.',
                                             'type': 'string'}},
                'type': 'object'},
 'safety': 'READ'}


def run(service, **kwargs):
    active = kwargs.get("workbench") or _active_workbench_name()
    pack = get_tool_pack(active)
    try:
        import FreeCADGui as Gui

        all_commands = sorted(Gui.listCommands())
    except Exception:
        all_commands = []

    prefixes = pack.command_prefixes if pack else ()
    commands = [
        name for name in all_commands
        if any(name.startswith(prefix) for prefix in prefixes)
    ] if prefixes else []
    visible, bounds = _bounded_items(commands, 120)
    return {
        "active_workbench": active,
        "domain": pack.domain if pack else None,
        "command_prefixes": list(prefixes),
        "tool_pack_enabled": service.is_workbench_tool_pack_enabled(active),
        "command_count": len(commands),
        "command_limit": bounds["limit"],
        "commands_truncated": bounds["truncated"],
        "commands_omitted": bounds["omitted"],
        "commands": visible,
    }


def _active_workbench_name():
    try:
        import FreeCADGui as Gui

        workbench = Gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None


def _bounded_items(items, limit):
    safe_limit = max(0, int(limit))
    visible = list(items[:safe_limit])
    omitted = max(0, len(items) - len(visible))
    return visible, {
        "limit": safe_limit,
        "truncated": omitted > 0,
        "omitted": omitted,
    }
