# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider abstraction for VibeCAD AI runtimes."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import json
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Callable


MAX_PROVIDER_IMAGE_BYTES = 2_000_000
OPENAI_REQUEST_DUMP_DIR_ENV = "VIBECAD_OPENAI_REQUEST_DUMP_DIR"
DEFAULT_OPENAI_REQUEST_DUMP_DIR = Path("/tmp/vibecad-openai-request-dumps")


class ProviderUnavailable(RuntimeError):
    pass


@dataclass
class ProviderResult:
    final_output: str
    raw: Any = None


ToolRunner = Callable[[str, str], dict[str, Any]]
CancellationCheck = Callable[[], bool]


class BaseProvider:
    def run(
        self,
        prompt: str,
        context: dict[str, Any],
        tool_runner: ToolRunner | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> ProviderResult:
        raise NotImplementedError


class OfflineProvider(BaseProvider):
    """Report that AI is unavailable without pretending to perform CAD work."""

    def run(
        self,
        prompt: str,
        context: dict[str, Any],
        tool_runner: ToolRunner | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> ProviderResult:
        if cancellation_check is not None and cancellation_check():
            raise ProviderUnavailable("VibeCAD run stopped by user.")
        workbench = context.get("workbench") or "unknown"
        return ProviderResult(
            "VibeCAD is offline. "
            f"Active workbench: {workbench}. "
            "Configure authentication before asking the AI provider."
        )


class OpenAIAgentsProvider(BaseProvider):
    """OpenAI Agents SDK adapter.

    The official quickstart pattern is Agent + Runner.run + function tools.
    This adapter keeps that dependency optional so FreeCAD can start without the
    SDK installed.
    """

    def __init__(
        self,
        model: str = "gpt-5.5",
        api_key: str | None = None,
        reasoning_effort: str = "high",
        timeout_seconds: float | None = None,
        max_turns: int | None = 80,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.max_turns = max_turns

    def run(
        self,
        prompt: str,
        context: dict[str, Any],
        tool_runner: ToolRunner | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> ProviderResult:
        try:
            return _run_agents_subprocess(
                prompt=prompt,
                context=context,
                tool_runner=tool_runner,
                model=self.model,
                api_key=self.api_key,
                reasoning_effort=self.reasoning_effort,
                timeout_seconds=self.timeout_seconds,
                max_turns=self.max_turns,
                cancellation_check=cancellation_check,
            )
        except TimeoutError as exc:
            if self.timeout_seconds and self.timeout_seconds > 0:
                raise ProviderUnavailable(
                    f"OpenAI Agents provider timed out after {self.timeout_seconds:g} seconds."
                ) from exc
            raise


@contextmanager
def _temporary_openai_key(api_key: str | None):
    if not api_key:
        yield
        return
    original = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = api_key
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = original


def _run_with_deadline(call: Callable[[], Any], timeout_seconds: float) -> Any:
    if (
        timeout_seconds <= 0
        or threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "SIGALRM")
    ):
        return call()

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(signum, frame):
        raise TimeoutError

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _run_agents_subprocess(
    *,
    prompt: str,
    context: dict[str, Any],
    tool_runner: ToolRunner | None,
    model: str,
    api_key: str | None,
    reasoning_effort: str | None,
    timeout_seconds: float | None,
    max_turns: int | None = 80,
    clear_inherited_modules: bool = True,
    event_pump: Callable[[], None] | None = None,
    cancellation_check: CancellationCheck | None = None,
) -> ProviderResult:
    multiprocessing_context = (
        multiprocessing.get_context("fork")
        if "fork" in multiprocessing.get_all_start_methods()
        else multiprocessing.get_context()
    )
    parent_conn, child_conn = multiprocessing_context.Pipe()
    process = multiprocessing_context.Process(
        target=_agents_child_main,
        args=(
            child_conn,
            prompt,
            context,
            model,
            api_key,
            reasoning_effort,
            timeout_seconds,
            max_turns,
            clear_inherited_modules,
        ),
    )
    process.daemon = True
    original_stdin = sys.stdin
    replacement_stdin = None
    try:
        if not hasattr(sys.stdin, "close"):
            replacement_stdin = open(os.devnull, "r", encoding="utf-8")
            sys.stdin = replacement_stdin
        process.start()
    finally:
        sys.stdin = original_stdin
        if replacement_stdin is not None:
            replacement_stdin.close()
    child_conn.close()

    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else None
    )
    pump_events = event_pump or _process_provider_wait_events
    try:
        while True:
            if cancellation_check is not None and cancellation_check():
                raise ProviderUnavailable("VibeCAD run stopped by user.")
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if deadline is not None and remaining <= 0:
                raise TimeoutError
            wait_seconds = 0.05 if remaining is None else min(0.05, remaining)
            if parent_conn.poll(wait_seconds):
                try:
                    message = parent_conn.recv()
                except EOFError as exc:
                    raise ProviderUnavailable(
                        "OpenAI Agents provider process ended before sending a result."
                    ) from exc
                message_type = message.get("type")
                if message_type == "tool":
                    if cancellation_check is not None and cancellation_check():
                        raise ProviderUnavailable("VibeCAD run stopped by user.")
                    result = _call_parent_tool(
                        tool_runner,
                        message.get("tool_name", ""),
                        message.get("arguments_json", "{}"),
                    )
                    parent_conn.send({"type": "tool_result", "result": result})
                elif message_type == "done":
                    process.join(timeout=0.2)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)
                    return ProviderResult(
                        final_output=str(message.get("final_output", "")),
                        raw=message.get("raw"),
                    )
                elif message_type == "error":
                    error = str(message.get("error", "unknown provider error"))
                    raise ProviderUnavailable(error)
            else:
                pump_events()

            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError

            if not process.is_alive():
                process.join(timeout=1)
                if process.exitcode == 0:
                    raise ProviderUnavailable("OpenAI Agents provider exited without a result.")
                raise ProviderUnavailable(
                    f"OpenAI Agents provider process exited with code {process.exitcode}."
                )
    finally:
        parent_conn.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=2)


def _process_provider_wait_events() -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    try:
        app.processEvents(QtCore.QEventLoop.AllEvents, 10)
    except TypeError:
        app.processEvents()


def _call_parent_tool(
    tool_runner: ToolRunner | None,
    tool_name: str,
    arguments_json: str,
) -> dict[str, Any]:
    if tool_runner is None:
        return {"ok": False, "error": "No VibeCAD tool runner is available."}
    try:
        return tool_runner(tool_name, arguments_json)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _model_visible_context(context: dict[str, Any]) -> dict[str, Any]:
    from provider_tools.core_get_current_freecad_context import _model_visible_context as visible

    return visible(context)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        return repr(value)


def _provider_tool_request_schema(tool: Any) -> dict[str, Any]:
    return {
        "function_name": getattr(tool, "name", None) or getattr(tool, "__name__", ""),
        "description": getattr(tool, "description", None)
        or getattr(tool, "__doc__", None)
        or "",
        "params_json_schema": _json_safe(getattr(tool, "params_json_schema", None)),
        "strict_json_schema": getattr(tool, "strict_json_schema", None),
        "callable": bool(getattr(tool, "on_invoke_tool", None) or callable(tool)),
    }


def _openai_request_dump_dir() -> Path | None:
    configured = os.environ.get(OPENAI_REQUEST_DUMP_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_OPENAI_REQUEST_DUMP_DIR


def _write_openai_request_dump(payload: dict[str, Any]) -> str | None:
    dump_dir = _openai_request_dump_dir()
    dump_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    timestamped = dump_dir / f"openai-request-{int(time.time() * 1000)}-{os.getpid()}.json"
    latest = dump_dir / "latest-openai-request.json"
    timestamped.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return str(timestamped)


def _build_provider_function_tools(
    context: dict[str, Any],
    conn: Any,
    FunctionTool: Any,
) -> list[Any]:
    from provider_tools import create_tool

    tools = []
    provider_function_tools = []
    for schema in context.get("provider_tool_schemas", []) or []:
        if not isinstance(schema, dict) or not schema.get("name"):
            continue
        tool_name = str(schema["name"])
        tool = create_tool(schema, conn, FunctionTool)
        tools.append(tool)
        provider_function_tools.append(
            {"tool_name": tool_name, "function_name": getattr(tool, "name", "")}
        )
    context["provider_function_tools"] = provider_function_tools
    return tools


def _build_context_function_tool(context: dict[str, Any], FunctionTool: Any) -> Any:
    from provider_tools import create_context_tool

    schema = {
        "name": "core.get_current_freecad_context",
        "description": "Return the current VibeCAD-visible FreeCAD context.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "workbench": "global",
        "safety": "read",
    }
    tool = create_context_tool(schema, context, FunctionTool)
    context.setdefault("provider_function_tools", []).insert(
        0,
        {"tool_name": schema["name"], "function_name": getattr(tool, "name", "")},
    )
    return tool


def _agents_child_main(
    conn,
    prompt: str,
    context: dict[str, Any],
    model: str,
    api_key: str | None,
    reasoning_effort: str | None,
    timeout_seconds: float | None,
    max_turns: int | None,
    clear_inherited_modules: bool,
) -> None:
    try:
        if clear_inherited_modules:
            _clear_inherited_sdk_modules()
        os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_MODEL_DATA", "true")
        os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_TOOL_DATA", "true")
        os.environ.setdefault("OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA", "false")
        import asyncio
        from agents import Agent, FunctionTool, RunConfig, Runner
        try:
            from agents import ModelSettings
        except Exception:
            ModelSettings = None
        try:
            from openai.types.shared import Reasoning
        except Exception:
            Reasoning = None
    except Exception as exc:
        conn.send(
            {
                "type": "error",
                "error": (
                    "OpenAI Agents SDK is not available. Install the optional "
                    f"'agents' package and configure authentication. ({exc})"
                ),
            }
        )
        conn.close()
        return

    model_settings = None
    if reasoning_effort and ModelSettings is not None:
        reasoning = (
            Reasoning(effort=reasoning_effort)
            if Reasoning is not None
            else {"effort": reasoning_effort}
        )
        model_settings = ModelSettings(reasoning=reasoning)

    provider_function_tools = _build_provider_function_tools(context, conn, FunctionTool)
    context_function_tool = _build_context_function_tool(context, FunctionTool)
    agent_kwargs = {
        "name": "VibeCAD",
        "instructions": (
            "You are VibeCAD, a native FreeCAD CAD operator.\n\n"
            "Operate by the current FreeCAD state, not by memory or prose. Use "
            "get_current_freecad_context when you need context. The current "
            "document, active workbench, task panel, screenshot observation, "
            "vibecad_loop.next_step, remaining_outcomes, and recent tool results "
            "are authoritative.\n\n"
            "Use the direct function tools exposed to you for this active "
            "workbench. Each function is a native FreeCAD operation with a "
            "single purpose. Do not invent tool names or route work through a "
            "generic dispatcher. Workbench-scoped function tools are refreshed "
            "after explicit workbench switches. If the native tool you need is "
            "owned by another workbench, call core.activate_workbench for that "
            "workbench and finish the current turn when VibeCAD returns the "
            "workbench-switch checkpoint; the next turn will expose that "
            "workbench's direct function tools. Do not report a tool-shape gap "
            "for a known native tool until you have tried switching to the "
            "owning workbench and inspecting the refreshed tool surface.\n\n"
            "Some native tools change the active edit/task context even when "
            "they are not explicit workbench switches. In particular, creating "
            "or opening a Sketch starts a Sketcher editing phase, and closing a "
            "ready Sketch can return work to PartDesign feature creation. When "
            "a tool returns checkpoint='tool_surface_refresh' or "
            "required_next_action.finish_current_turn, stop that provider turn "
            "with concise progress. VibeCAD will immediately refresh the direct "
            "callable tools and continue the same user goal in the next turn. "
            "Do not report a tool-shape gap for tools that are expected after "
            "that refresh.\n\n"
            "Drive FreeCAD the way a skilled human operator would with native "
            "tools. Choose the workbench and operations that fit the requested "
            "CAD outcome, then build editable model structure instead of visual "
            "stand-ins. For parametric PartDesign results, use Body, Sketcher "
            "constraints, and PartDesign features when those are the native "
            "operations that make the design robust. Do not use Part primitive "
            "shortcuts as substitutes for sketch-feature modeling. For true "
            "assemblies, make usable component objects, switch to "
            "AssemblyWorkbench, and use native assembly functions when they "
            "appear in the refreshed tool surface.\n\n"
            "Work autonomously in small meaningful steps: inspect state, perform "
            "the next CAD action, inspect the returned result, and continue. "
            "Respect checkpoint/deferred tool results by ending the current turn "
            "with concise progress so VibeCAD can refresh context and call you "
            "again. If a tool fails, use the returned error, next_action, "
            "required_next_action, sketch profile status, document state, or "
            "screenshot state to recover with another available tool. Aim for a "
            "coherent completed design increment, not endless optional detail "
            "expansion; once the requested design is represented well enough for "
            "CAD review and visual inspection is satisfied, report completion.\n\n"
            "Assume reasonable CAD defaults when the user did not specify them: "
            "millimeters, sensible origin/plane choices, and standard workbench "
            "conventions. Ask a question only when continuing would be "
            "destructive, impossible, or materially ambiguous.\n\n"
            "Do not report completion until remaining_outcomes is empty or the "
            "current document and screenshot state prove the requested CAD result "
            "is coherent. For visible models, capture and inspect a viewport "
            "screenshot before final completion."
        ),
        "model": model,
        "tools": [
            context_function_tool,
            *provider_function_tools,
        ],
    }
    if model_settings is not None:
        agent_kwargs["model_settings"] = model_settings
    agent = Agent(**agent_kwargs)

    async def _run() -> Any:
        agent_input = _agents_input_from_context(prompt, _model_visible_context(context))
        _write_openai_request_dump(
            {
                "schema": "vibecad-openai-agents-request-v1",
                "created_at_unix": time.time(),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "max_turns": max_turns,
                "timeout_seconds": timeout_seconds,
                "agent": {
                    "name": agent_kwargs["name"],
                    "instructions": agent_kwargs["instructions"],
                    "tools": [
                        _provider_tool_request_schema(tool)
                        for tool in agent_kwargs["tools"]
                    ],
                    "model_settings": _json_safe(model_settings),
                },
                "run": {
                    "input": agent_input,
                    "run_config": {"tracing_disabled": True},
                    "max_turns": max_turns,
                },
                "model_visible_context": _model_visible_context(context),
            }
        )
        run_task = Runner.run(
            agent,
            agent_input,
            run_config=RunConfig(tracing_disabled=True),
            max_turns=max_turns,
        )
        if timeout_seconds is not None and timeout_seconds > 0:
            return await asyncio.wait_for(run_task, timeout=timeout_seconds)
        return await run_task

    try:
        with _temporary_openai_key(api_key):
            result = asyncio.run(_run())
        conn.send({"type": "done", "final_output": result.final_output, "raw": None})
    except TimeoutError:
        timeout_text = (
            f"{timeout_seconds:g} seconds"
            if timeout_seconds is not None and timeout_seconds > 0
            else "the configured deadline"
        )
        conn.send(
            {
                "type": "error",
                "error": f"OpenAI Agents provider timed out after {timeout_text}.",
            }
        )
    except Exception as exc:
        conn.send({"type": "error", "error": str(exc)})
    finally:
        conn.close()


def _agents_input_from_context(prompt: str, context: dict[str, Any]) -> str | list[dict[str, Any]]:
    screenshot = context.get("view_screenshot")
    if not isinstance(screenshot, dict) or not screenshot.get("captured"):
        return prompt
    path_text = screenshot.get("path")
    if not path_text:
        return prompt
    try:
        path = Path(str(path_text))
        if not path.is_file():
            return prompt
        size = path.stat().st_size
        if size <= 0 or size > MAX_PROVIDER_IMAGE_BYTES:
            return prompt
        suffix = path.suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix)
        if mime_type is None:
            return prompt
        image_url = (
            f"data:{mime_type};base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii")
        )
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    {
                        "type": "input_image",
                        "image_url": image_url,
                        "detail": "auto",
                    },
                ],
            }
        ]
    except Exception:
        return prompt


def _clear_inherited_sdk_modules() -> None:
    for name in list(sys.modules):
        if (
            name == "agents"
            or name.startswith("agents.")
            or name == "pydantic"
            or name.startswith("pydantic.")
            or name == "openai"
            or name.startswith("openai.")
        ):
            sys.modules.pop(name, None)
