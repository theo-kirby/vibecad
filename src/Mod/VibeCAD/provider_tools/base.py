# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared factory for explicit VibeCAD provider function tools."""

from __future__ import annotations

from typing import Any


def tool_description(schema: dict[str, Any]) -> str:
    tool_name = str(schema.get("name", ""))
    description = str(schema.get("description", "")).strip()
    workbench = schema.get("workbench") or "global"
    safety = schema.get("safety") or "unknown"
    return (
        f"{description}\n\n"
        f"Native VibeCAD tool: {tool_name}. Workbench: {workbench}. Safety: {safety}. "
        "Use this exact function directly."
    ).strip()


def tool_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    result = dict(parameters)
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    if result.get("type") == "object":
        result.setdefault("additionalProperties", False)
    return result


def create_provider_tool(
    tool_name: str,
    function_name: str,
    schema: dict[str, Any],
    conn: Any,
    FunctionTool: Any,
) -> Any:
    async def _invoke(_tool_context, arguments_json: str):
        conn.send(
            {
                "type": "tool",
                "tool_name": tool_name,
                "arguments_json": arguments_json or "{}",
            }
        )
        response = conn.recv()
        if response.get("type") != "tool_result":
            return {"ok": False, "error": "Invalid VibeCAD tool bridge response."}
        return response.get("result", {"ok": False, "error": "Missing tool result."})

    return FunctionTool(
        name=function_name,
        description=tool_description(schema),
        params_json_schema=tool_json_schema(schema),
        on_invoke_tool=_invoke,
        strict_json_schema=False,
    )
