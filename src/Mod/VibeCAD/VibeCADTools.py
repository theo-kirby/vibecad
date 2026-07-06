# SPDX-License-Identifier: LGPL-2.1-or-later

"""Structured tool registry used by VibeCAD providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class SafetyLevel(str, Enum):
    READ = "read"
    VIEW = "view"
    SAFE_WRITE = "safe_write"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"
    DEVELOPER = "developer"


@dataclass(frozen=True)
class VibeCADTool:
    name: str
    description: str
    handler: Callable[..., Any]
    safety: SafetyLevel = SafetyLevel.READ
    parameters: dict[str, Any] = field(default_factory=dict)
    workbench: str | None = None
    contextual: bool = False

    def is_available_for(self, workbench: str | None) -> bool:
        if self.workbench is None:
            return True
        if workbench is None:
            return True
        return self.workbench == workbench

    def to_schema(self, active_workbench: str | None = None) -> dict[str, Any]:
        availability = "global"
        if self.workbench:
            availability = "workbench_exact"
        elif self.contextual:
            availability = "workbench_contextual"
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
            "safety": self.safety.value,
            "workbench": self.workbench,
            "active_workbench": active_workbench,
            "availability": availability,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, VibeCADTool] = {}

    def register(self, tool: VibeCADTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"VibeCAD tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> VibeCADTool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, workbench: str | None = None) -> list[dict[str, Any]]:
        result = []
        for tool in self._tools.values():
            if not tool.is_available_for(workbench):
                continue
            result.append(tool.to_schema(active_workbench=workbench))
        return result

    def call(self, tool_name: str, **kwargs: Any) -> Any:
        return self.get(tool_name).handler(**kwargs)
