# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared helpers for CAM machining service tools."""

from __future__ import annotations

from typing import Any


LINEAR_AXIS_DIRECTIONS = {
    "X": (1, 0, 0),
    "Y": (0, 1, 0),
    "Z": (0, 0, 1),
}

ROTARY_AXIS_DIRECTIONS = {
    "A": (1, 0, 0),
    "B": (0, 1, 0),
    "C": (0, 0, 1),
}


def resolve_machine(machine_name: str | None) -> Any | None:
    """Resolve a Machine by display name from user assets or built-in templates."""
    if not machine_name:
        return None
    from Machine.models import MachineFactory

    try:
        return MachineFactory.get_machine(machine_name)
    except (FileNotFoundError, ValueError):
        pass
    wanted = str(machine_name).lower()
    for display_name, path in MachineFactory.list_builtin_templates():
        if display_name.lower() == wanted:
            try:
                return MachineFactory.load_configuration(path)
            except Exception:
                return None
    return None


def available_machine_names() -> list[str]:
    """List machine display names from user assets and built-in templates."""
    from Machine.models import MachineFactory

    names: list[str] = []
    try:
        for name, path in MachineFactory.list_configuration_files():
            if path is not None:
                names.append(name)
    except Exception:
        pass
    try:
        for display_name, _path in MachineFactory.list_builtin_templates():
            if display_name not in names:
                names.append(display_name)
    except Exception:
        pass
    return names


def max_toolhead_rpm(machine: Any) -> float | None:
    """Highest max_rpm across the machine's toolheads, or None when unset."""
    limits = [
        float(toolhead.max_rpm)
        for toolhead in getattr(machine, "toolheads", [])
        if float(getattr(toolhead, "max_rpm", 0) or 0) > 0
    ]
    return max(limits) if limits else None


def machine_summary(machine: Any) -> dict[str, Any]:
    """Summarize a Machine object for tool responses."""
    linear_axes = {}
    for name, axis in getattr(machine, "linear_axes", {}).items():
        linear_axes[name] = {
            "min_limit": float(axis.min_limit),
            "max_limit": float(axis.max_limit),
            "max_velocity": float(axis.max_velocity),
        }
    rotary_axes = {}
    for name, axis in getattr(machine, "rotary_axes", {}).items():
        rotary_axes[name] = {
            "min_limit": float(axis.min_limit),
            "max_limit": float(axis.max_limit),
            "max_velocity": float(axis.max_velocity),
        }
    toolheads = []
    for toolhead in getattr(machine, "toolheads", []):
        toolheads.append(
            {
                "name": getattr(toolhead, "name", None),
                "max_rpm": float(getattr(toolhead, "max_rpm", 0) or 0),
                "min_rpm": float(getattr(toolhead, "min_rpm", 0) or 0),
                "max_power_kw": float(getattr(toolhead, "max_power_kw", 0) or 0),
            }
        )
    output = getattr(machine, "output", None)
    return {
        "name": getattr(machine, "name", None),
        "manufacturer": getattr(machine, "manufacturer", None),
        "postprocessor": getattr(machine, "postprocessor_file_name", None),
        "linear_axes": linear_axes,
        "rotary_axes": rotary_axes,
        "toolheads": toolheads,
        "output_tool_length_offset": bool(getattr(output, "output_tool_length_offset", False)),
    }


def job_tool_controllers(job: Any) -> list[Any]:
    """Return the tool controllers attached to a job (may be empty)."""
    tools = getattr(job, "Tools", None)
    group = getattr(tools, "Group", None)
    return list(group) if group else []


def tool_controller_summary(tc: Any) -> dict[str, Any]:
    """Summarize a tool controller for tool responses."""
    item = {
        "name": getattr(tc, "Name", None),
        "label": getattr(tc, "Label", None),
        "tool_number": int(getattr(tc, "ToolNumber", 0) or 0),
        "spindle_speed": float(getattr(tc, "SpindleSpeed", 0) or 0),
    }
    tool = getattr(tc, "Tool", None)
    if tool is not None:
        item["tool"] = {
            "name": getattr(tool, "Name", None),
            "label": getattr(tool, "Label", None),
        }
        diameter = getattr(tool, "Diameter", None)
        if diameter is not None:
            try:
                item["tool"]["diameter"] = float(getattr(diameter, "Value", diameter))
            except (TypeError, ValueError):
                pass
    return item


def no_job_error(requested: str | None) -> dict[str, Any]:
    """Standard recoverable response when a CAM job cannot be resolved."""
    return {
        "ok": False,
        "error": (
            f"CAM job not found: {requested}" if requested else "No CAM job in the active document."
        ),
        "requested": requested,
        "recoverable": True,
        "next_actions": [
            {
                "tool": "cam.create_job",
                "why": "Create a CAM job for a model before adding tools or operations.",
            },
        ],
    }
