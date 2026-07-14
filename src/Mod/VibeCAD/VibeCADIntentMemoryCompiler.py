# SPDX-License-Identifier: LGPL-2.1-or-later

"""Private provider call that compiles durable project intent.

This is deliberately separate from the CAD agent loop.  The provider receives
one forced structured tool and cannot call FreeCAD operations or return prose
that VibeCAD then scrapes.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from VibeCADIntentMemory import (
    active_memory_context,
    compiler_tool_schema,
)
from VibeCADProvider import (
    CancellationCheck,
    ProgressCallback,
    ProviderUnavailable,
    _capture_outbound_request,
    _clear_inherited_sdk_modules,
    _json_safe,
    _run_provider_subprocess,
)


COMPILER_INSTRUCTIONS = """You maintain VibeCAD Intent Memory.

Call the supplied commit_intent_memory_update function exactly once. Classify
every uncovered conversation turn in the supplied order. Preserve durable
customer intent: intended outcomes, requirements, constraints, accepted
decisions, components, interfaces, mechanisms, manufacturing requirements,
verification obligations, assumptions, open questions, and explicitly rejected
directions. Use concise standalone statements that remain meaningful without the
conversation transcript.

Do not store mutable CAD state, feature progress, object names created during a
run, tool narration, provider errors, apologies, or conversational filler. Do
not silently turn model proposals into user requirements. Use user_explicit only
for a direct user statement, user_confirmed for a proposal the user accepted,
and model_assumption only for an unresolved engineering assumption that must
remain visible. Supersede contradicted entries explicitly. Cite every durable
statement with the exact source turn IDs supplied. Never invent a turn ID.
"""


def _compiler_prompt(
    memory: dict[str, Any],
    uncovered_turns: list[dict[str, Any]],
    legacy_design_markdown: str,
) -> str:
    payload: dict[str, Any] = {
        "intent_memory": active_memory_context(memory),
        "uncovered_turns": uncovered_turns,
    }
    legacy = str(legacy_design_markdown or "").strip()
    if legacy and not memory.get("exists"):
        payload["legacy_design_markdown"] = legacy
        payload["legacy_migration_rule"] = (
            "Use this only as a candidate summary. Retain a statement only when "
            "the supplied conversation provenance supports it."
        )
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _parse_json_arguments(raw: Any, *, provider: str) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except ValueError as exc:
        raise RuntimeError(
            f"{provider} Intent Memory tool arguments were not valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{provider} Intent Memory tool arguments were not an object.")
    return parsed


def _openai_compiler_child_main(
    conn,
    prompt: str,
    context: dict[str, Any],
    model: str,
    api_key: str | None,
    _reasoning_effort: str | None,
    timeout_seconds: float | None,
    _max_turns: int | None,
    clear_inherited_modules: bool,
    base_url: str | None = None,
) -> None:
    try:
        if clear_inherited_modules:
            _clear_inherited_sdk_modules()
        from openai import OpenAI

        schema = compiler_tool_schema()
        tool_name = schema["name"]
        request: dict[str, Any] = {
            "model": model,
            "instructions": COMPILER_INSTRUCTIONS,
            "input": prompt,
            "tools": [
                {
                    "type": "function",
                    "name": tool_name,
                    "description": schema["description"],
                    "parameters": schema["parameters"],
                }
            ],
            "tool_choice": {"type": "function", "name": tool_name},
            "parallel_tool_calls": False,
            "stream": False,
        }
        client_kwargs: dict[str, Any] = {
            "api_key": api_key or ("vibecad-local" if base_url else None),
            "max_retries": 2,
        }
        if not client_kwargs["api_key"]:
            raise ProviderUnavailable("No OpenAI-compatible API key is configured.")
        if base_url:
            client_kwargs["base_url"] = base_url
        if timeout_seconds is not None and timeout_seconds > 0:
            client_kwargs["timeout"] = timeout_seconds
        _capture_outbound_request(
            context,
            provider="openai",
            sdk_call="OpenAI.responses.create.intent_memory",
            turn=1,
            request=request,
            base_url=base_url,
        )
        response = OpenAI(**client_kwargs).responses.create(**request)
        calls = [
            item
            for item in list(getattr(response, "output", []) or [])
            if str(getattr(item, "type", "") or "") == "function_call"
        ]
        if len(calls) != 1:
            raise RuntimeError(
                "OpenAI-compatible Intent Memory compiler did not return exactly "
                "one structured tool call."
            )
        call = calls[0]
        if str(getattr(call, "name", "") or "") != tool_name:
            raise RuntimeError("OpenAI-compatible compiler called the wrong function.")
        update = _parse_json_arguments(
            getattr(call, "arguments", "{}"), provider="OpenAI-compatible"
        )
        conn.send({"type": "done", "final_output": "", "raw": _json_safe(update)})
    except Exception as exc:
        conn.send({"type": "error", "error": str(exc)})
    finally:
        conn.close()


def _anthropic_compiler_child_main(
    conn,
    prompt: str,
    context: dict[str, Any],
    model: str,
    api_key: str | None,
    _reasoning_effort: str | None,
    timeout_seconds: float | None,
    _max_turns: int | None,
    clear_inherited_modules: bool,
    base_url: str | None = None,
) -> None:
    try:
        if clear_inherited_modules:
            _clear_inherited_sdk_modules()
        import anthropic

        if not api_key:
            raise ProviderUnavailable("No Anthropic API key is configured.")
        schema = compiler_tool_schema()
        tool_name = schema["name"]
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "system": COMPILER_INSTRUCTIONS,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": tool_name,
                    "description": schema["description"],
                    "input_schema": schema["parameters"],
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        client_kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2}
        if base_url:
            client_kwargs["base_url"] = base_url
        if timeout_seconds is not None and timeout_seconds > 0:
            client_kwargs["timeout"] = timeout_seconds
        _capture_outbound_request(
            context,
            provider="anthropic",
            sdk_call="Anthropic.messages.create.intent_memory",
            turn=1,
            request=request,
            base_url=base_url,
        )
        response = anthropic.Anthropic(**client_kwargs).messages.create(**request)
        calls = [
            block
            for block in list(getattr(response, "content", []) or [])
            if str(getattr(block, "type", "") or "") == "tool_use"
        ]
        if len(calls) != 1:
            raise RuntimeError(
                "Anthropic Intent Memory compiler did not return exactly one "
                "structured tool call."
            )
        call = calls[0]
        if str(getattr(call, "name", "") or "") != tool_name:
            raise RuntimeError("Anthropic compiler called the wrong function.")
        update = getattr(call, "input", None)
        if not isinstance(update, dict):
            raise RuntimeError("Anthropic Intent Memory tool input was not an object.")
        conn.send({"type": "done", "final_output": "", "raw": _json_safe(update)})
    except Exception as exc:
        conn.send({"type": "error", "error": str(exc)})
    finally:
        conn.close()


def compile_intent_memory_update(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    memory: dict[str, Any],
    uncovered_turns: list[dict[str, Any]],
    legacy_design_markdown: str = "",
    debug_context: dict[str, Any] | None = None,
    cancellation_check: CancellationCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Run one isolated, forced-tool compiler request and return its arguments."""
    clean_provider = str(provider or "").strip().lower()
    if clean_provider not in {"openai", "anthropic"}:
        raise ValueError(f"Unsupported Intent Memory provider: {provider!r}.")
    if not uncovered_turns:
        raise ValueError("Intent Memory compiler requires at least one uncovered turn.")
    child_main: Callable[..., None] = (
        _anthropic_compiler_child_main
        if clean_provider == "anthropic"
        else _openai_compiler_child_main
    )
    context = dict(debug_context or {})
    context["intent_memory_request"] = {
        "provider": clean_provider,
        "model": model,
        "base_revision": memory.get("revision"),
        "uncovered_turn_count": len(uncovered_turns),
    }
    result = _run_provider_subprocess(
        prompt=_compiler_prompt(memory, uncovered_turns, legacy_design_markdown),
        context=context,
        tool_runner=None,
        model=model,
        api_key=api_key,
        reasoning_effort=None,
        timeout_seconds=timeout_seconds,
        max_turns=1,
        base_url=base_url,
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
        child_main=child_main,
        provider_label="VibeCAD Intent Memory compiler",
    )
    if not isinstance(result.raw, dict):
        raise RuntimeError("Intent Memory compiler returned no structured update.")
    return dict(result.raw)
