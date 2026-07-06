# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.report_tool_shape_gap``."""

from __future__ import annotations

import time


TOOL_SPEC = {'description': "Record the AI model's in-run critique of a missing, ambiguous, "
                'or weak native CAD tool/context shape.',
 'name': 'core.report_tool_shape_gap',
 'parameters': {'properties': {'active_workbench': {'description': 'Workbench where '
                                                                   'this tool or context '
                                                                   'shape is needed.',
                                                    'type': 'string'},
                               'current_workaround': {'description': 'What workaround '
                                                                     'was attempted, '
                                                                     'if any.',
                                                      'type': 'string'},
                               'desired_native_tool': {'description': 'The native '
                                                                      'FreeCAD-style '
                                                                      'tool shape that '
                                                                      'should exist.',
                                                       'type': 'string'},
                               'missing_capability': {'description': 'The CAD '
                                                                     'capability that '
                                                                     'was missing or '
                                                                     'too weak.',
                                                      'type': 'string'},
                               'needed_result_data': {'description': 'Result fields the '
                                                                     'model needs after '
                                                                     'calling this tool '
                                                                     'or related tools.',
                                                      'type': 'string'},
                               'needed_schema': {'description': 'Schema parameters or '
                                                               'tool split/rename '
                                                               'changes the model '
                                                               'needs.',
                                                'type': 'string'},
                               'severity': {'description': 'Impact level such as '
                                                          'blocker, high, medium, '
                                                          'or low.',
                                            'type': 'string'},
                               'tool_or_class': {'description': 'Specific tool name or '
                                                               'missing tool class.',
                                                'type': 'string'},
                               'why_blocks_quality': {'description': 'Why this gap '
                                                                     'blocks high-quality '
                                                                     'AI CAD operation.',
                                                      'type': 'string'},
                               'why_needed': {'description': 'Why this capability is '
                                                             "needed for the user's "
                                                             'design.',
                                              'type': 'string'}},
                'type': 'object'},
 'safety': 'SAFE_WRITE'}


def run(service, **kwargs):
    missing_capability = _first_text(
        kwargs,
        "missing_capability",
        "tool_or_class",
        default="unspecified tool/context shape gap",
    )
    why_needed = _first_text(
        kwargs,
        "why_needed",
        "why_blocks_quality",
        default="No explanation provided.",
    )
    desired_native_tool = _first_text(
        kwargs,
        "desired_native_tool",
        "tool_or_class",
        default=missing_capability,
    )
    item = {
        "feedback_id": f"tool-shape-{len(service._tool_shape_feedback) + 1}",
        "missing_capability": missing_capability,
        "why_needed": why_needed,
        "desired_native_tool": desired_native_tool,
        "tool_or_class": _first_text(kwargs, "tool_or_class", default=desired_native_tool),
        "severity": _first_text(kwargs, "severity", default="unspecified"),
        "why_blocks_quality": _first_text(kwargs, "why_blocks_quality", default=why_needed),
        "needed_schema": _first_text(kwargs, "needed_schema", default=""),
        "needed_result_data": _first_text(kwargs, "needed_result_data", default=""),
        "current_workaround": str(kwargs.get("current_workaround", "")).strip(),
        "active_workbench": str(kwargs.get("active_workbench", "")).strip() or _active_workbench_name(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    service._tool_shape_feedback.append(item)
    service._tool_shape_feedback = service._tool_shape_feedback[-40:]
    return {
        "ok": True,
        "recorded": item,
        "feedback_id": item["feedback_id"],
        "feedback_count": len(service._tool_shape_feedback),
        "recent_feedback": service._tool_shape_feedback[-10:],
    }


def _first_text(kwargs, *keys, default=""):
    for key in keys:
        value = kwargs.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return str(default)


def _active_workbench_name():
    try:
        import FreeCADGui as Gui

        workbench = Gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None
