# SPDX-License-Identifier: LGPL-2.1-or-later

"""Authoritative VibeCAD tool contracts and runtime registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator


class SafetyLevel(str, Enum):
    READ = "read"
    VIEW = "view"
    SAFE_WRITE = "safe_write"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"
    DEVELOPER = "developer"


EDIT_MODE_NONE = "none"
EDIT_MODE_SKETCH = "sketch"
VALID_EDIT_MODES = frozenset({EDIT_MODE_NONE, EDIT_MODE_SKETCH})


@dataclass(frozen=True)
class ToolSpec:
    """Single source of truth for one provider-callable operation."""

    name: str
    description: str
    parameters: dict[str, Any]
    safety: SafetyLevel
    workbench: str | None
    contextual: bool
    requires_document: bool
    edit_modes: frozenset[str]
    provider_visible: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ToolSpec":
        name = str(raw.get("name") or "").strip()
        if not name or "." not in name:
            raise ValueError(f"Invalid VibeCAD tool name: {name!r}")
        description = str(raw.get("description") or "").strip()
        if len(description) < 24:
            raise ValueError(
                f"Tool {name} needs a concrete provider description, not a label."
            )
        parameters = deepcopy(raw.get("parameters"))
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError(f"Tool {name} parameters must be a JSON object schema.")
        if not isinstance(parameters.get("properties"), dict):
            raise ValueError(f"Tool {name} parameter schema needs properties.")
        try:
            Draft202012Validator.check_schema(parameters)
        except Exception as exc:
            raise ValueError(f"Tool {name} has an invalid JSON schema: {exc}") from exc
        safety_name = str(raw.get("safety") or "READ").strip().upper()
        try:
            safety = SafetyLevel[safety_name]
        except KeyError as exc:
            raise ValueError(
                f"Tool {name} has unknown safety {safety_name!r}."
            ) from exc
        workbench = str(raw.get("workbench") or "").strip() or None
        contextual = bool(raw.get("contextual", False))
        requires_document = bool(
            raw.get(
                "requires_document",
                bool(workbench)
                or safety in {SafetyLevel.SAFE_WRITE, SafetyLevel.WRITE},
            )
        )
        raw_modes = raw.get("edit_modes")
        if raw_modes is None:
            if safety in {SafetyLevel.READ, SafetyLevel.VIEW}:
                modes = set(VALID_EDIT_MODES)
            elif workbench == "SketcherWorkbench":
                modes = {EDIT_MODE_SKETCH}
            else:
                modes = {EDIT_MODE_NONE}
        else:
            if not isinstance(raw_modes, (list, tuple, set, frozenset)):
                raise ValueError(f"Tool {name} edit_modes must be a list of modes.")
            modes = {str(item).strip() for item in raw_modes}
        unknown_modes = modes - VALID_EDIT_MODES
        if unknown_modes:
            raise ValueError(
                f"Tool {name} has unknown edit modes: {sorted(unknown_modes)}."
            )
        if not modes:
            raise ValueError(f"Tool {name} must allow at least one edit mode.")
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            safety=safety,
            workbench=workbench,
            contextual=contextual,
            requires_document=requires_document,
            edit_modes=frozenset(modes),
            provider_visible=bool(raw.get("provider_visible", True)),
        )

    def supports_edit_mode(self, edit_mode: str) -> bool:
        return str(edit_mode or EDIT_MODE_NONE) in self.edit_modes

    def validate_arguments(self, arguments: Mapping[str, Any]) -> None:
        errors = sorted(
            Draft202012Validator(self.parameters).iter_errors(dict(arguments)),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if not errors:
            return
        error = _most_specific_schema_error(errors[0])
        path = ".".join(str(item) for item in error.absolute_path)
        location = f" at {path}" if path else ""
        raise ValueError(
            f"Invalid arguments for {self.name}{location}: {error.message}"
        )

    def to_schema(self, active_workbench: str | None = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": deepcopy(self.parameters),
            "safety": self.safety.value,
            "workbench": self.workbench,
            "active_workbench": active_workbench,
            "requires_document": self.requires_document,
            "edit_modes": sorted(self.edit_modes),
        }


@dataclass(frozen=True)
class VibeCADTool:
    spec: ToolSpec
    handler: Callable[..., Any]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.spec.parameters

    @property
    def safety(self) -> SafetyLevel:
        return self.spec.safety

    @property
    def workbench(self) -> str | None:
        return self.spec.workbench

    @property
    def contextual(self) -> bool:
        return self.spec.contextual

    def to_schema(self, active_workbench: str | None = None) -> dict[str, Any]:
        return self.spec.to_schema(active_workbench)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, VibeCADTool] = {}

    def register(self, tool: VibeCADTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"VibeCAD tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def register_spec(
        self,
        raw_spec: Mapping[str, Any],
        handler: Callable[..., Any],
    ) -> VibeCADTool:
        tool = VibeCADTool(spec=ToolSpec.from_mapping(raw_spec), handler=handler)
        self.register(tool)
        return tool

    def get(self, name: str) -> VibeCADTool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, workbench: str | None = None) -> list[dict[str, Any]]:
        return [
            tool.to_schema(active_workbench=workbench)
            for tool in self._tools.values()
            if tool.spec.provider_visible
        ]

    def call(self, tool_name: str, **kwargs: Any) -> Any:
        tool = self.get(tool_name)
        tool.spec.validate_arguments(kwargs)
        return tool.handler(**kwargs)


def _most_specific_schema_error(error: Any) -> Any:
    leaves: list[Any] = []

    def collect(item: Any) -> None:
        children = list(getattr(item, "context", []) or [])
        if not children:
            leaves.append(item)
            return
        for child in children:
            collect(child)

    collect(error)
    if not leaves:
        return error
    priority = {
        "enum": 6,
        "type": 5,
        "required": 4,
        "additionalProperties": 3,
        "minimum": 2,
        "exclusiveMinimum": 2,
        "const": 0,
    }
    return max(
        leaves,
        key=lambda item: (
            len(list(getattr(item, "absolute_path", []) or [])),
            priority.get(str(getattr(item, "validator", "")), 1),
            -len(str(getattr(item, "message", ""))),
        ),
    )
