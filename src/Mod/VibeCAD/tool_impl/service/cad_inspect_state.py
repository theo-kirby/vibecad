# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native design state inspection."""

from __future__ import annotations

from typing import Any


TOOL_SPEC = {
    "name": "cad.inspect_state",
    "description": (
        "Return the current design state in CAD terms: document, active edit "
        "state, accepted design memory, requested objects, and report errors."
    ),
    "safety": "READ",
    "parameters": {
        "type": "object",
        "properties": {
            "object_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional object names or labels to inspect.",
            },
            "include_errors": {"type": "boolean"},
            "include_design_memory": {"type": "boolean"},
        },
    },
}


def run(
    service: Any,
    object_names: list[str] | None = None,
    include_errors: bool = True,
    include_design_memory: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "active_workbench": service.active_workbench_name(),
        "document": service.document_summary(),
        "task_panel": service.task_panel_summary(),
    }
    if include_design_memory:
        project = service.project_context()
        result["design_memory"] = project.get("design_memory", {})
        result["project"] = {
            "root": project.get("root"),
            "manifest_path": project.get("manifest_path"),
        }
    if include_errors:
        result["report_view_errors"] = service.registry.call(
            "core.get_report_view_errors", include_stale=False
        )
    inspected = []
    for raw_name in object_names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        inspected.append(
            service.registry.call("core.get_object_properties", object_name=name)
        )
    if inspected:
        result["objects"] = inspected
    return result
