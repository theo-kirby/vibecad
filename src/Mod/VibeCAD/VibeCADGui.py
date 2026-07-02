# SPDX-License-Identifier: LGPL-2.1-or-later

"""GUI commands that existing workbenches can register natively."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import FreeCAD as App
import FreeCADGui as Gui

from VibeCADCore import get_service
from VibeCADProject import PHASE_ORDER
from VibeCADSession import _format_document_delta, run_prompt
from VibeCADWorkbenchTools import get_tool_pack


COMMANDS = [
    "VibeCAD_AskAI",
    "VibeCAD_ExplainSelection",
    "VibeCAD_OpenAssistant",
    "VibeCAD_OpenPreferences",
    "VibeCAD_AuthStatus",
]

CONTEXT_COMMANDS = [
    "VibeCAD_ExplainSelection",
    "VibeCAD_OpenAssistant",
    "VibeCAD_AskAI",
]

_commands_registered = False
_preferences_registered = False
_workbench_manipulator = None
_workbench_activation_connected = False
_assistant_dock_restoring = False
_assistant_screen_events_connected = False
_assistant_screen_change_handler = None
_document_observer_connected = False
_document_observer = None
_document_save_conversations: dict[str, list[dict[str, Any]]] = {}

_ASSISTANT_DOCK_PREF_GROUP = "User parameter:BaseApp/Preferences/Mod/VibeCAD/AssistantDock"


class _AssistantRunController:
    """Single source of truth for the active GUI-launched provider loop."""

    def __init__(self) -> None:
        self._run_id = 0
        self._active = False
        self._cancel_requested = False

    def begin(self) -> int:
        self._run_id += 1
        self._active = True
        self._cancel_requested = False
        return self._run_id

    def request_cancel(self) -> bool:
        if not self._active:
            return False
        self._cancel_requested = True
        return True

    def finish(self, run_id: int) -> None:
        if run_id != self._run_id:
            return
        self._active = False
        self._cancel_requested = False

    def is_cancelled(self, run_id: int) -> bool:
        return run_id != self._run_id or self._cancel_requested

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "active": self._active,
            "cancel_requested": self._cancel_requested,
        }


_assistant_run_controller = _AssistantRunController()


class _WorkbenchManipulator:
    """Expose VibeCAD commands in C++-backed workbenches."""

    def modifyMenuBar(self) -> list[dict[str, str]]:
        return [
            {"append": command, "menuItem": "Std_DlgParameter"}
            for command in COMMANDS
        ]

    def modifyToolBars(self) -> list[dict[str, str]]:
        return [
            {"append": command, "toolBar": "File"}
            for command in COMMANDS
        ]


def _print(message: str) -> None:
    App.Console.PrintMessage(f"{message}\n")


def _warn(message: str) -> None:
    App.Console.PrintWarning(f"{message}\n")


_IDLE_THINKING_TEXT = "AI thinking:\nIdle."
_IDLE_RUN_STATUS_TEXT = "Ready. Tell VibeCAD what to make or change."


def _set_run_status_label(label: Any, text: str, *, show_idle: bool = False) -> None:
    if label is None:
        return
    clean = str(text or "").strip()
    label.setText(clean)
    label.setVisible(
        bool(clean)
        and (show_idle or clean not in {_IDLE_RUN_STATUS_TEXT} and not clean.startswith("Mode:"))
    )


def _show_thinking_box(thinking: Any, text: str) -> None:
    if thinking is None:
        return
    clean = str(text or "").strip()
    thinking.setPlainText(clean)
    thinking.setVisible(bool(clean) and clean != _IDLE_THINKING_TEXT)


def _append_output(text: str) -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        _print(text)
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    output = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput") if dock else None
    if output is None:
        _print(text)
        return
    current = output.toPlainText().strip()
    output.setPlainText(f"{current}\n\n{text}".strip())
    from PySide import QtGui

    output.moveCursor(QtGui.QTextCursor.End)


def _append_thinking(text: str) -> None:
    clean = str(text or "").strip()
    if not clean:
        return
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    thinking = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADThinking") if dock else None
    if thinking is None:
        return
    current = thinking.toPlainText().strip()
    if current in {"", _IDLE_THINKING_TEXT}:
        _show_thinking_box(thinking, f"AI thinking:\n{clean}")
    else:
        _show_thinking_box(thinking, f"{current}\n\n{clean}")
    from PySide import QtGui

    thinking.moveCursor(QtGui.QTextCursor.End)


def _storage_role_for_conversation(role: str) -> str | None:
    return {
        "User": "user",
        "VibeCAD": "assistant",
        "System": "system",
    }.get(str(role))


def _record_conversation_turn(
    role: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    storage_role = _storage_role_for_conversation(role)
    clean = str(text or "").strip()
    if storage_role is None or not clean:
        return
    try:
        get_service().record_conversation_turn(storage_role, clean, metadata=metadata)
    except Exception as exc:
        _warn(f"VibeCAD conversation save failed: {exc}")


def _format_saved_conversation(conversation: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    labels = {
        "user": "User",
        "assistant": "VibeCAD",
        "system": "System",
    }
    for entry in conversation:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role", ""))
        content = str(entry.get("content", "")).strip()
        label = labels.get(role)
        if label is None or not content:
            continue
        lines.append(f"{label}:\n{content}")
    return "\n\n".join(lines)


def _render_saved_conversation(dock: Any | None = None) -> None:
    if _is_assistant_run_active():
        return
    try:
        from PySide import QtGui, QtWidgets
    except Exception:
        return

    if dock is None:
        main_window = Gui.getMainWindow()
        dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel") if main_window else None
    output = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput") if dock else None
    if output is None:
        return
    try:
        history = get_service().conversation_history()
    except Exception as exc:
        _warn(f"VibeCAD conversation load failed: {exc}")
        return
    output.setPlainText(_format_saved_conversation(history.get("conversation", [])))
    output.setProperty("VibeCADConversationPath", str(history.get("path", "")))
    output.moveCursor(QtGui.QTextCursor.End)


def _append_conversation(
    role: str,
    text: str,
    *,
    persist: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    clean = str(text or "").strip()
    if not clean:
        return
    if role == "AI thinking":
        _append_thinking(clean)
        return
    _append_output(f"{role}:\n{clean}")
    if persist:
        _record_conversation_turn(role, clean, metadata=metadata)


def _set_tool_trace(tool_trace: list[dict[str, Any]]) -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    trace_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADToolTrace") if dock else None
    if trace_box is None:
        return
    if not tool_trace:
        trace_box.setPlainText("No provider tool calls yet.")
        return
    lines = []
    for index, entry in enumerate(tool_trace, start=1):
        status = "ok" if entry.get("ok") else "blocked"
        result = entry.get("result") or {}
        suffix = ""
        if result.get("title"):
            suffix = f" | {result['title']}"
        elif result.get("error"):
            suffix = f" | {result['error']}"
        lines.append(
            f"{index}. {status} | {entry.get('safety', 'unknown')} | "
            f"{entry.get('tool_name', 'unknown')}{suffix}"
        )
    trace_box.setPlainText("\n".join(lines))


def _format_progress_event(event: dict[str, Any]) -> str:
    name = str(event.get("event", "progress"))
    if name == "context_build_started":
        return "Looking at the current FreeCAD document..."
    if name == "context_build_completed":
        return "I have the document context."
    if name == "provider_turn_started":
        base = "Thinking about the next CAD move..."
        delta = _format_document_delta(event.get("document_delta"))
        if delta and not delta.startswith("not available"):
            return f"{base} | {delta}"
        return base
    if name == "provider_turn_completed":
        return "CAD step completed."
    if name == "provider_turn_failed":
        return (
            f"Provider turn {event.get('turn', '?')} failed: "
            f"{event.get('error', 'unknown error')}"
        )
    if name == "provider_total_timeout":
        return (
            f"Autonomous loop reached {event.get('elapsed_seconds', 0):.1f}s | "
            f"tools: {event.get('tool_count', 0)}"
        )
    if name == "provider_run_cancelled":
        return "Run stopped by user."
    if name == "human_steering_consumed":
        return "Applied your latest correction."
    if name == "tool_call_completed":
        status = "ok" if event.get("ok") else "blocked"
        result = event.get("result", {}) if isinstance(event.get("result"), dict) else {}
        if result.get("title"):
            return f"CAD action {status}: {result['title']}"
        if result.get("error"):
            return f"CAD action {status}: {result['error']}"
        return f"CAD action {status}: {event.get('tool_name', 'unknown')}"
    return name.replace("_", " ")


def _handle_progress_event(dock: Any, event: dict[str, Any], tool_trace: list[dict[str, Any]]) -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    text = _format_progress_event(event)
    run_status = dock.findChild(QtWidgets.QLabel, "VibeCADRunStatus") if dock else None
    thinking_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADThinking") if dock else None
    if run_status is not None:
        _set_run_status_label(run_status, text, show_idle=True)
    if thinking_box is not None:
        current = thinking_box.toPlainText().strip()
        line = text
        if not current.endswith(line):
            if current in {"", _IDLE_THINKING_TEXT}:
                _show_thinking_box(thinking_box, f"AI thinking:\n{line}")
            else:
                _show_thinking_box(thinking_box, f"{current}\n\n{line}".strip())
            from PySide import QtGui

            thinking_box.moveCursor(QtGui.QTextCursor.End)
    if event.get("event") == "tool_call_completed":
        _set_tool_trace(tool_trace)
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()


def _set_screenshot_status(summary: dict[str, Any]) -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    status = dock.findChild(QtWidgets.QLabel, "VibeCADScreenshotStatus") if dock else None
    if status is None:
        return
    if summary.get("captured"):
        size = summary.get("size") or ["?", "?"]
        text = (
            f"View attached: {size[0]}x{size[1]} | {summary.get('camera_type', 'camera')}"
        )
    elif summary.get("error"):
        text = f"View not attached: {summary['error']}"
    else:
        text = ""
    status.setText(text)
    status.setVisible(bool(text))


def _capture_view_from_panel() -> None:
    summary = get_service().capture_view_screenshot()
    _set_screenshot_status(summary)
    if summary.get("captured"):
        _append_conversation(
            "AI thinking",
            "Attached viewport screenshot: "
            f"{summary.get('size', ['?', '?'])} {summary.get('camera_type', 'camera')}"
        )
    else:
        _append_conversation("VibeCAD", f"Viewport screenshot failed: {summary.get('error', 'unknown error')}")
    _refresh_workbench_context()


def _is_assistant_run_active() -> bool:
    return bool(_assistant_run_controller.snapshot()["active"])


def _is_assistant_cancel_requested() -> bool:
    return bool(_assistant_run_controller.snapshot()["cancel_requested"])


def _pump_assistant_ui_events() -> None:
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


def _sync_dock_run_properties(dock: Any) -> None:
    if dock is None:
        return
    dock.setProperty("VibeCADRunActive", _is_assistant_run_active())
    dock.setProperty("VibeCADCancelRequested", _is_assistant_cancel_requested())


def _render_assistant_run_state(dock: Any, text: str | None = None) -> None:
    _sync_dock_run_properties(dock)
    _set_prompt_busy(dock, _is_assistant_run_active(), text=text)


def _set_prompt_busy(dock: Any, busy: bool, text: str | None = None) -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    run_button = dock.findChild(QtWidgets.QPushButton, "VibeCADRunPrompt") if dock else None
    stop_button = dock.findChild(QtWidgets.QPushButton, "VibeCADStopPrompt") if dock else None
    prompt_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt") if dock else None
    capture_button = dock.findChild(QtWidgets.QPushButton, "VibeCADCaptureView") if dock else None
    run_status = dock.findChild(QtWidgets.QLabel, "VibeCADRunStatus") if dock else None

    if run_button is not None:
        run_button.setEnabled(True)
        run_button.setText("Steer" if busy else "Send")
    if stop_button is not None:
        stop_button.setEnabled(busy)
    if prompt_box is not None:
        try:
            phase_context = get_service().phase_context()
        except Exception:
            phase_context = {}
        phase = str(phase_context.get("active_phase") or "intent")
        intent = phase_context.get("intent", {}) if isinstance(phase_context, dict) else {}
        approved_intent = bool(intent.get("approved")) if isinstance(intent, dict) else False
        prompt_box.setReadOnly(False)
        prompt_box.setPlaceholderText(
            "Steer the current CAD run..."
            if busy
            else _phase_prompt_placeholder(phase, approved_intent)
        )
    if capture_button is not None:
        capture_button.setEnabled(not busy)
    if run_status is not None:
        status_text = text or (
            (
                "Stopping after the current provider/tool step..."
                if _is_assistant_cancel_requested()
                else "Working. Type a correction in the same box and send it."
            )
            if busy
            else _IDLE_RUN_STATUS_TEXT
        )
        _set_run_status_label(run_status, status_text, show_idle=busy)

def _stop_prompt_from_panel() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is None:
        return
    if not _is_assistant_run_active():
        _render_assistant_run_state(dock)
        return
    _assistant_run_controller.request_cancel()
    _render_assistant_run_state(dock, text="Stopping after the current provider/tool step...")
    _pump_assistant_ui_events()
    run_status = dock.findChild(QtWidgets.QLabel, "VibeCADRunStatus")
    if run_status is not None:
        _set_run_status_label(run_status, "Stopping after the current provider/tool step...", show_idle=True)
    _append_conversation("User", "Stop.", persist=True, metadata={"source": "stop"})
    _append_conversation("AI thinking", "Stopping after the current provider/tool step.")


def _run_prompt_from_panel() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        _print("VibeCAD assistant panel requires Qt.")
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is None:
        return

    prompt_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt")
    if prompt_box is None:
        return

    run_status = dock.findChild(QtWidgets.QLabel, "VibeCADRunStatus")
    prompt = prompt_box.toPlainText().strip()
    if not prompt:
        if run_status is not None:
            _set_run_status_label(run_status, "Enter a message before sending.", show_idle=True)
        return

    service = get_service()
    if _is_assistant_run_active():
        result = service.queue_steering_message(prompt)
        if result.get("ok"):
            prompt_box.clear()
            _append_conversation("User", prompt, persist=True, metadata={"source": "steering"})
            _append_conversation("AI thinking", "Received. I will apply that to the current CAD run.")
            _refresh_phase_context()
        else:
            _append_conversation(
                "VibeCAD",
                result.get("error", "Unable to send correction."),
                persist=True,
                metadata={"source": "steering_error"},
            )
        return

    prefer_online = service.use_online_provider_by_default()
    run_id = _assistant_run_controller.begin()
    _render_assistant_run_state(dock)
    _pump_assistant_ui_events()
    _append_conversation("User", prompt, persist=True, metadata={"source": "prompt"})
    thinking_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADThinking")
    if thinking_box is not None:
        _show_thinking_box(thinking_box, "AI thinking:\nStarting.")
    prompt_box.clear()
    live_tool_trace: list[dict[str, Any]] = []

    def _cancelled() -> bool:
        return _assistant_run_controller.is_cancelled(run_id)

    def _steering_messages() -> list[str]:
        return [
            str(item.get("text", "")).strip()
            for item in service.consume_steering_messages()
            if str(item.get("text", "")).strip()
        ]

    def _progress(event: dict[str, Any]) -> None:
        _render_assistant_run_state(dock)
        if event.get("event") == "tool_call_completed":
            live_tool_trace.append(
                {
                    "tool_name": event.get("tool_name"),
                    "active_workbench": event.get("active_workbench"),
                    "ok": bool(event.get("ok")),
                    "safety": event.get("safety", "unknown"),
                    "result": event.get("result", {}),
                }
            )
        _handle_progress_event(dock, event, live_tool_trace)

    try:
        _pump_assistant_ui_events()
        response = run_prompt(
            prompt,
            service=service,
            prefer_online=prefer_online,
            progress_callback=_progress,
            cancellation_check=_cancelled,
            steering_check=_steering_messages,
        )
        error = f"\nProvider note: {response.error}" if response.error else ""
        _append_conversation(
            "VibeCAD",
            f"{response.final_output}{error}",
        )
        _set_tool_trace(response.tool_trace)
    except Exception as exc:
        _append_conversation(
            "VibeCAD",
            f"The CAD run failed: {exc}",
            persist=True,
            metadata={"source": "prompt_exception"},
        )
    finally:
        _assistant_run_controller.finish(run_id)
        _render_saved_conversation(dock)
        _render_assistant_run_state(dock)
        _refresh_pending_actions()
        _refresh_action_history()
        _refresh_phase_context()


def _friendly_status(value: Any) -> str:
    return str(value or "unknown").replace("_", " ")


def _friendly_workbench(value: str | None) -> str:
    if not value:
        return "none"
    return value.removesuffix("Workbench") or value


def _phase_label(phase: str) -> str:
    return {
        "intent": "Intent",
        "design": "Design",
        "assembly": "Assembly",
        "analysis": "Analysis",
        "manufacturing": "Manufacturing",
    }.get(str(phase), str(phase).title())


def _phase_banner_text(
    phase: str,
    approved_intent: bool,
    validation_ok: bool,
) -> str:
    if phase == "intent":
        return "Tell VibeCAD what you want. It should state assumptions, call out risks, and start CAD work when the design direction is clear enough."
    if phase == "design":
        return "Designing or revising editable CAD geometry. Existing models should be modified in place unless you explicitly ask for a rebuild."
    if phase == "assembly":
        return "Working on component relationships, placements, and assembly structure."
    if phase == "analysis":
        return "Working on load cases, materials, mesh, and analysis evidence."
    if phase == "manufacturing":
        return "Working on stock, setup, tooling, operations, and manufacturability."
    suffix = "ready" if validation_ok else "needs validation"
    return f"Current CAD state: {suffix}."


def _phase_prompt_placeholder(phase: str, approved_intent: bool) -> str:
    if phase == "intent":
        return "Message VibeCAD..."
    if phase == "design":
        return "Message VibeCAD..."
    if phase == "assembly":
        return "Describe the assembly..."
    if phase == "analysis":
        return "Describe the analysis..."
    if phase == "manufacturing":
        return "Describe manufacturing intent..."
    return "Message VibeCAD..."


def _set_combo_current_data(combo, value: str) -> None:
    index = combo.findData(value)
    if index < 0:
        return
    previous = combo.blockSignals(True)
    try:
        combo.setCurrentIndex(index)
    finally:
        combo.blockSignals(previous)


def _selected_mode_phase() -> str | None:
    try:
        from PySide import QtWidgets
    except Exception:
        return None

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel") if main_window else None
    selector = dock.findChild(QtWidgets.QComboBox, "VibeCADModeSelector") if dock else None
    if selector is None:
        return None
    value = selector.currentData()
    return str(value) if value else None


def _mode_changed_from_panel(index: int) -> None:
    phase = _selected_mode_phase()
    if not phase:
        return
    try:
        result = get_service().set_phase(
            phase,
            reason="Selected in the VibeCAD panel.",
            requested_by="user",
        )
    except Exception as exc:
        _warn(f"VibeCAD mode change failed: {exc}")
        return
    _refresh_phase_context()
    _refresh_workbench_context()
    _refresh_pending_actions()
    _refresh_action_history()
    try:
        from PySide import QtWidgets
    except Exception:
        return
    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel") if main_window else None
    run_status = dock.findChild(QtWidgets.QLabel, "VibeCADRunStatus") if dock else None
    if run_status is not None:
        _set_run_status_label(
            run_status,
            f"Mode: {_phase_label(str(result.get('active_phase') or phase))}.",
        )


def _workflow_audit_summary_lines(audit: dict[str, Any]) -> list[str]:
    ok = bool(audit.get("ok")) if isinstance(audit, dict) else False
    gates = audit.get("gates", []) if isinstance(audit, dict) else []
    failures = audit.get("failures", []) if isinstance(audit, dict) else []
    passed = sum(
        1 for gate in gates
        if isinstance(gate, dict) and gate.get("passed")
    )
    total = len(gates) if isinstance(gates, list) else 0
    lines = [
        "Workflow audit: passed" if ok else "Workflow audit: needs attention",
        f"Gates: {passed}/{total} | Failed: {len(failures)}",
    ]
    if failures:
        failed_names = [
            str(item.get("name"))
            for item in failures
            if isinstance(item, dict) and item.get("name")
        ]
        lines.append("Failed: " + (", ".join(failed_names) or "unknown"))
    else:
        lines.append("Failed gates: none")
    lines.append(str(audit.get("next_action") or ""))
    return lines


def _refresh_phase_context() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is None:
        return
    service = get_service()
    try:
        phase_context = service.phase_context()
    except Exception:
        phase_context = {}
    phase = str(phase_context.get("active_phase") or "intent")
    intent = phase_context.get("intent", {}) if isinstance(phase_context, dict) else {}
    approved_intent = bool(intent.get("approved")) if isinstance(intent, dict) else False
    selector = dock.findChild(QtWidgets.QComboBox, "VibeCADModeSelector")
    if selector is not None:
        _set_combo_current_data(selector, phase)
    prompt_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt")
    if prompt_box is not None:
        busy = _is_assistant_run_active()
        prompt_box.setPlaceholderText(
            "Steer the current CAD run..."
            if busy
            else _phase_prompt_placeholder(phase, approved_intent)
        )


def _pending_action_ids() -> list[str]:
    service = get_service()
    return [item["id"] for item in service.pending_actions()["pending"]]


def _selected_action_id() -> str | None:
    try:
        from PySide import QtWidgets
    except Exception:
        return None

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    selector = dock.findChild(QtWidgets.QComboBox, "VibeCADActionSelector") if dock else None
    if selector is None:
        return None
    value = selector.currentData()
    return str(value) if value else None


def _refresh_pending_actions() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    pending_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPendingActions") if dock else None
    selector = dock.findChild(QtWidgets.QComboBox, "VibeCADActionSelector") if dock else None
    if pending_box is None:
        return

    pending = get_service().pending_actions()["pending"]
    if selector is not None:
        current = selector.currentData()
        selector.clear()
        for item in pending:
            selector.addItem(f"{item['id']} | {item['title']}", item["id"])
        if current:
            index = selector.findData(current)
            if index >= 0:
                selector.setCurrentIndex(index)
    if not pending:
        pending_box.setPlainText("No pending actions.")
        return
    lines = []
    for item in pending:
        lines.append(
            f"{item['id']} | {item['safety']} | {item['title']}\n{item['description']}"
        )
    pending_box.setPlainText("\n\n".join(lines))


def _refresh_action_history() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    history_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADActionHistory") if dock else None
    if history_box is None:
        return

    history = get_service().action_history()["history"]
    if not history:
        history_box.setPlainText("No approved or rejected actions yet.")
        return
    lines = []
    for item in history[-12:]:
        status = item.get("status", "unknown")
        title = item.get("title", "Untitled action")
        detail = ""
        result = item.get("result")
        if isinstance(result, dict):
            if result.get("ok") is False and result.get("error"):
                detail = f" | {result['error']}"
            elif isinstance(result.get("verification"), dict):
                detail = f" | verified: {bool(result['verification'].get('ok', True))}"
                delta = result.get("document_delta")
                if isinstance(delta, dict):
                    detail += f" | objects: {delta.get('object_count_delta', 0):+d}"
                report_errors = result.get("report_view_errors")
                if isinstance(report_errors, dict) and report_errors.get("errors"):
                    detail += f" | report errors: {len(report_errors['errors'])}"
        lines.append(f"{item.get('id', 'action')} | {status} | {title}{detail}")
    history_box.setPlainText("\n".join(lines))


def _refresh_workbench_context() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is None:
        return
    commands_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADWorkbenchCommands")
    templates_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADObjectTemplates")
    objects_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADWorkbenchObjects")
    provider_tools_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADProviderTools")
    tool_trace_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADToolTrace")
    report_errors_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADReportErrors")
    screenshot_status = dock.findChild(QtWidgets.QLabel, "VibeCADScreenshotStatus")
    part_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPartContext")
    mesh_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADMeshContext")
    points_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPointsContext")
    material_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADMaterialContext")
    sketcher_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADSketcherContext")
    spreadsheet_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADSpreadsheetContext")
    draft_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADDraftContext")
    partdesign_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPartDesignContext")
    techdraw_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADTechDrawContext")
    fem_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADFemContext")
    cam_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADCamContext")
    bim_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADBimContext")
    assembly_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADAssemblyContext")
    inspection_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADInspectionContext")
    openscad_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOpenSCADContext")
    surface_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADSurfaceContext")
    reen_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADReverseEngineeringContext")
    robot_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADRobotContext")
    meshpart_box = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADMeshPartContext")
    service = get_service()
    commands = service.workbench_command_summary()
    templates = service.workbench_object_templates()["templates"]
    objects = service.workbench_object_summary()["objects"]
    provider_surface = service.provider_phase_tool_surface()
    provider_tools = provider_surface["tools"]
    report_errors = service.report_view_errors()
    part = service.part_summary()
    mesh = service.mesh_summary()
    points = service.points_summary()
    material = service.material_summary()
    sketcher = service.sketcher_summary()
    spreadsheet = service.spreadsheet_summary()
    draft = service.draft_summary()
    partdesign = service.partdesign_summary()
    techdraw = service.techdraw_summary()
    fem = service.fem_summary()
    cam = service.cam_summary()
    bim = service.bim_summary()
    assembly = service.assembly_summary()
    inspection = service.inspection_summary()
    openscad = service.openscad_summary()
    surface = service.surface_summary()
    reen = service.reverseengineering_summary()
    robot = service.robot_summary()
    meshpart = service.meshpart_summary()
    if commands_box is not None:
        names = commands["commands"][:40]
        suffix = "" if len(commands["commands"]) <= 40 else "\n..."
        commands_box.setPlainText(
            f"{commands['command_count']} matching commands\n"
            + "\n".join(names)
            + suffix
        )
    if templates_box is not None:
        lines = [
            f"{item['name']} | {item['object_type']}"
            for item in templates
        ]
        templates_box.setPlainText("\n".join(lines) if lines else "No object templates.")
    if objects_box is not None:
        lines = [
            f"{item['name']} | {item['label']} | {item['type']}"
            for item in objects
        ]
        objects_box.setPlainText("\n".join(lines) if lines else "No workbench-owned objects.")
    if provider_tools_box is not None:
        scope = provider_surface.get("scope", {}) if isinstance(provider_surface, dict) else {}
        lines = [
            f"{item['name']} | {item['safety']} | {item['availability']}"
            for item in provider_tools
        ]
        prefix = ""
        if isinstance(scope, dict) and scope.get("phase"):
            prefix = (
                f"Phase surface: {scope.get('phase')} | "
                f"{provider_surface.get('tool_count', len(lines))}/"
                f"{provider_surface.get('full_workbench_tool_count', len(lines))} tools\n"
            )
        provider_tools_box.setPlainText(prefix + ("\n".join(lines) if lines else "No provider tools."))
    if tool_trace_box is not None and not tool_trace_box.toPlainText().strip():
        tool_trace_box.setPlainText("No provider tool calls yet.")
    if report_errors_box is not None:
        errors = report_errors.get("errors") or []
        if errors:
            report_errors_box.setPlainText(
                f"Report errors: {len(errors)}\n" + "\n".join(errors[-8:])
            )
        elif report_errors.get("captured"):
            report_errors_box.setPlainText("No report-view errors detected.")
        else:
            reason = report_errors.get("reason", "report view unavailable")
            report_errors_box.setPlainText(f"Report-view errors unavailable: {reason}")
    if screenshot_status is not None:
        _set_screenshot_status(service.view_screenshot_summary())
    if part_box is not None:
        if part["object_count"]:
            lines = [
                f"{item['name']} | {item['label']} | {item['type']}"
                for item in part["objects"][:8]
            ]
            part_box.setPlainText(
                f"Part objects: {part['object_count']}\n" + "\n".join(lines)
            )
        else:
            part_box.setPlainText("No Part context.")
    if mesh_box is not None:
        if mesh["object_count"]:
            lines = [
                f"{item['name']} | {item['label']} | Facets: {item.get('mesh', {}).get('facets', 0)}"
                for item in mesh["objects"][:8]
            ]
            mesh_box.setPlainText(
                f"Mesh objects: {mesh['object_count']}\n" + "\n".join(lines)
            )
        else:
            mesh_box.setPlainText("No Mesh context.")
    if points_box is not None:
        if points["object_count"]:
            lines = [
                f"{item['name']} | {item['label']} | Points: {item['point_count']}"
                for item in points["objects"][:8]
            ]
            points_box.setPlainText(
                f"Point clouds: {points['object_count']}\n" + "\n".join(lines)
            )
        else:
            points_box.setPlainText("No Points context.")
    if material_box is not None:
        if material["object_count"]:
            lines = []
            for item in material["objects"][:8]:
                color = item.get("diffusecolor") or item.get("first_shape_diffuse_color") or "none"
                lines.append(
                    f"{item['name']} | {item['label']} | "
                    f"Color: {color} | Appearance slots: {item.get('shape_appearance_count')}"
                )
            material_box.setPlainText(
                f"Material-capable objects: {material['object_count']}\n" + "\n".join(lines)
            )
        else:
            material_box.setPlainText("No Material context.")
    if sketcher_box is not None:
        if sketcher["found"]:
            sketch = sketcher["sketch"]
            sketcher_box.setPlainText(
                f"{sketch['name']} | {sketch['label']}\n"
                f"Geometry: {sketcher['geometry_count']} | "
                f"Constraints: {sketcher['constraint_count']}"
            )
        else:
            sketcher_box.setPlainText("No Sketcher sketch context.")
    if spreadsheet_box is not None:
        if spreadsheet["found"]:
            sheet = spreadsheet["sheet"]
            spreadsheet_box.setPlainText(
                f"{sheet['name']} | {sheet['label']}\n"
                f"Non-empty cells: {spreadsheet['non_empty_count']}"
            )
        else:
            spreadsheet_box.setPlainText("No Spreadsheet context.")
    if draft_box is not None:
        if draft["object_count"]:
            lines = [
                f"{item['name']} | {item['label']} | {item['type']}"
                for item in draft["objects"][:8]
            ]
            draft_box.setPlainText(
                f"Draft objects: {draft['object_count']}\n" + "\n".join(lines)
            )
        else:
            draft_box.setPlainText("No Draft context.")
    if partdesign_box is not None:
        if partdesign["body_count"]:
            lines = []
            for body in partdesign["bodies"][:6]:
                tip = body["tip"]["name"] if body["tip"] else "none"
                lines.append(
                    f"{body['name']} | {body['label']} | "
                    f"Features: {body['feature_count']} | Tip: {tip}"
                )
            partdesign_box.setPlainText(
                f"PartDesign bodies: {partdesign['body_count']}\n" + "\n".join(lines)
            )
        else:
            partdesign_box.setPlainText("No PartDesign context.")
    if techdraw_box is not None:
        if techdraw["page_count"]:
            lines = []
            for page in techdraw["pages"][:6]:
                template = page["template"]["name"] if page["template"] else "none"
                lines.append(
                    f"{page['name']} | {page['label']} | "
                    f"Views: {page['view_count']} | Template: {template}"
                )
            techdraw_box.setPlainText(
                f"TechDraw pages: {techdraw['page_count']}\n" + "\n".join(lines)
            )
        else:
            techdraw_box.setPlainText("No TechDraw context.")
    if fem_box is not None:
        if fem["analysis_count"]:
            lines = []
            for analysis in fem["analyses"][:6]:
                lines.append(
                    f"{analysis['name']} | {analysis['label']} | "
                    f"Members: {analysis['member_count']}"
                )
            fem_box.setPlainText(
                f"FEM analyses: {fem['analysis_count']}\n" + "\n".join(lines)
            )
        else:
            fem_box.setPlainText("No FEM context.")
    if cam_box is not None:
        if cam["job_count"]:
            lines = []
            for job in cam["jobs"][:6]:
                operations = job["operations"]["object_count"] if job["operations"] else 0
                tools = job["tools"]["object_count"] if job["tools"] else 0
                lines.append(
                    f"{job['name']} | {job['label']} | "
                    f"Operations: {operations} | Tools: {tools}"
                )
            cam_box.setPlainText(
                f"CAM jobs: {cam['job_count']}\n" + "\n".join(lines)
            )
        else:
            cam_box.setPlainText("No CAM context.")
    if bim_box is not None:
        if bim["object_count"]:
            lines = []
            for obj in bim["objects"][:6]:
                ifc_type = obj["ifc_type"] or "Unclassified"
                lines.append(
                    f"{obj['name']} | {obj['label']} | "
                    f"IfcType: {ifc_type} | Children: {obj['child_count']}"
                )
            bim_box.setPlainText(
                f"BIM objects: {bim['object_count']}\n" + "\n".join(lines)
            )
        else:
            bim_box.setPlainText("No BIM context.")
    if assembly_box is not None:
        if assembly["assembly_count"]:
            lines = []
            for asm in assembly["assemblies"][:6]:
                lines.append(
                    f"{asm['name']} | {asm['label']} | "
                    f"Components: {asm['components']} | Joints: {asm['joints']}"
                )
            assembly_box.setPlainText(
                f"Assemblies: {assembly['assembly_count']}\n" + "\n".join(lines)
            )
        else:
            assembly_box.setPlainText("No Assembly context.")
    if inspection_box is not None:
        if inspection["feature_count"] or inspection["candidate_count"]:
            lines = [
                f"{item['name']} | {item['label']} | Actual: "
                f"{item['actual']['name'] if item.get('actual') else 'none'} | "
                f"Nominals: {item['nominal_count']}"
                for item in inspection["features"][:6]
            ]
            if not lines:
                lines = [
                    f"{item['name']} | {item['label']} | {item['type']}"
                    for item in inspection["candidates"][:6]
                ]
            inspection_box.setPlainText(
                f"Inspection features: {inspection['feature_count']} | "
                f"Candidates: {inspection['candidate_count']}\n" + "\n".join(lines)
            )
        else:
            inspection_box.setPlainText("No Inspection context.")
    if openscad_box is not None:
        if openscad["object_count"]:
            lines = []
            for item in openscad["objects"][:6]:
                detail = item.get("proxy_type") or item["type"]
                lines.append(f"{item['name']} | {item['label']} | {detail}")
            openscad_box.setPlainText(
                f"OpenSCAD objects: {openscad['object_count']} | "
                f"Executable: {'yes' if openscad['openscad_executable_configured'] else 'no'}\n"
                + "\n".join(lines)
            )
        else:
            openscad_box.setPlainText(
                "No OpenSCAD context. Executable: "
                + ("yes" if openscad["openscad_executable_configured"] else "no")
            )
    if surface_box is not None:
        if surface["object_count"]:
            lines = []
            for item in surface["objects"][:6]:
                detail = item.get("boundarylist", item.get("boundaryedges", item.get("nsections", 0)))
                lines.append(
                    f"{item['name']} | {item['label']} | {item['type']} | Refs: {detail}"
                )
            surface_box.setPlainText(
                f"Surface features: {surface['object_count']}\n" + "\n".join(lines)
            )
        else:
            surface_box.setPlainText("No Surface context.")
    if reen_box is not None:
        if reen["candidate_count"] or reen["reconstruction_count"]:
            lines = [
                f"{item['name']} | {item['label']} | {item['type']}"
                for item in reen["candidates"][:4]
            ]
            lines += [
                f"{item['name']} | {item['label']} | {item['type']} | Fit"
                for item in reen["reconstructions"][:4]
            ]
            reen_box.setPlainText(
                f"ReverseEngineering candidates: {reen['candidate_count']} | "
                f"Fits: {reen['reconstruction_count']}\n" + "\n".join(lines)
            )
        else:
            reen_box.setPlainText("No ReverseEngineering context.")
    if robot_box is not None:
        if robot["robot_count"] or robot["trajectory_count"]:
            lines = [
                f"{item['name']} | {item['label']} | Robot"
                for item in robot["robots"][:4]
            ]
            lines += [
                f"{item['name']} | {item['label']} | Waypoints: {item.get('waypoint_count', 0)}"
                for item in robot["trajectories"][:4]
            ]
            robot_box.setPlainText(
                f"Robots: {robot['robot_count']} | "
                f"Trajectories: {robot['trajectory_count']}\n" + "\n".join(lines)
            )
        else:
            robot_box.setPlainText("No Robot context.")
    if meshpart_box is not None:
        if meshpart["part_candidate_count"] or meshpart["mesh_count"]:
            lines = [
                f"{item['name']} | {item['label']} | {item['type']}"
                for item in meshpart["part_candidates"][:4]
            ]
            lines += [
                f"{item['name']} | {item['label']} | Facets: {item.get('mesh', {}).get('facets', 0)}"
                for item in meshpart["meshes"][:4]
            ]
            meshpart_box.setPlainText(
                f"MeshPart candidates: {meshpart['part_candidate_count']} | "
                f"Meshes: {meshpart['mesh_count']}\n" + "\n".join(lines)
            )
        else:
            meshpart_box.setPlainText("No MeshPart context.")

    active_workbench = service.active_workbench_name()
    active_contexts = {
        "AssemblyWorkbench": {assembly_box},
        "BIMWorkbench": {bim_box},
        "CAMWorkbench": {cam_box},
        "DraftWorkbench": {draft_box},
        "FemWorkbench": {fem_box},
        "InspectionWorkbench": {inspection_box},
        "MaterialWorkbench": {material_box},
        "MeshWorkbench": {mesh_box},
        "MeshPartWorkbench": {meshpart_box},
        "OpenSCADWorkbench": {openscad_box},
        "PartDesignWorkbench": {partdesign_box},
        "PartWorkbench": {part_box},
        "PointsWorkbench": {points_box},
        "ReverseEngineeringWorkbench": {reen_box},
        "RobotWorkbench": {robot_box},
        "SketcherWorkbench": {sketcher_box},
        "SpreadsheetWorkbench": {spreadsheet_box},
        "SurfaceWorkbench": {surface_box},
        "TechDrawWorkbench": {techdraw_box},
    }.get(active_workbench, set())
    for context_box in (
        part_box,
        mesh_box,
        points_box,
        material_box,
        sketcher_box,
        spreadsheet_box,
        draft_box,
        partdesign_box,
        techdraw_box,
        fem_box,
        cam_box,
        bim_box,
        assembly_box,
        inspection_box,
        openscad_box,
        surface_box,
        reen_box,
        robot_box,
        meshpart_box,
    ):
        if context_box is not None:
            is_active_context = context_box in active_contexts
            context_box.setProperty("VibeCADContextActive", is_active_context)
            context_box.setVisible(False)


def _apply_selected_action() -> None:
    action_id = _selected_action_id()
    if action_id is None:
        ids = _pending_action_ids()
        action_id = ids[0] if ids else None
    if action_id is None:
        _append_output("No pending action to approve.")
        _refresh_pending_actions()
        return
    result = get_service().apply_action(action_id)
    _append_output(f"Approved {action_id}:\n{result}")
    _refresh_pending_actions()
    _refresh_action_history()
    _refresh_workbench_context()


def _reject_selected_action() -> None:
    action_id = _selected_action_id()
    if action_id is None:
        ids = _pending_action_ids()
        action_id = ids[0] if ids else None
    if action_id is None:
        _append_output("No pending action to reject.")
        _refresh_pending_actions()
        return
    result = get_service().reject_action(action_id)
    _append_output(f"Rejected {action_id}:\n{result}")
    _refresh_pending_actions()
    _refresh_action_history()


def _revise_selected_action() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    action_id = _selected_action_id()
    if action_id is None:
        ids = _pending_action_ids()
        action_id = ids[0] if ids else None
    if action_id is None:
        _append_output("No pending action to revise.")
        _refresh_pending_actions()
        return

    service = get_service()
    action = next(
        (
            item
            for item in service.pending_actions()["pending"]
            if item.get("id") == action_id
        ),
        None,
    )
    if action is None:
        _append_output(f"Pending action is no longer available: {action_id}")
        _refresh_pending_actions()
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    prompt = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt") if dock else None
    if prompt is None:
        _append_output("VibeCAD prompt box is unavailable.")
        return

    metadata = action.get("metadata") or {}
    prompt.setPlainText(
        "Revise this pending VibeCAD action before I approve it.\n\n"
        f"Action ID: {action.get('id')}\n"
        f"Title: {action.get('title')}\n"
        f"Safety: {action.get('safety')}\n"
        f"Workbench: {action.get('workbench') or service.active_workbench_name() or 'none'}\n"
        f"Description: {action.get('description')}\n"
        f"Metadata: {json.dumps(metadata, sort_keys=True)}\n\n"
        "Keep the original action pending. Propose a replacement action that "
        "addresses this revision request: "
    )
    prompt.setFocus()
    _append_output(f"Loaded {action_id} into the prompt for revision.")


def _undo_last_vibecad_action() -> None:
    result = get_service().undo_last_vibecad_action()
    _append_output(f"Undo last VibeCAD action:\n{result}")
    _refresh_pending_actions()
    _refresh_action_history()
    _refresh_workbench_context()


def _clear_local_session_from_panel() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    result = get_service().clear_local_session()
    if dock is not None:
        output = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput")
        prompt = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt")
        trace = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADToolTrace")
        if output is not None:
            output.clear()
        if prompt is not None:
            prompt.clear()
        if trace is not None:
            trace.setPlainText("No provider tool calls yet.")
    _set_screenshot_status(get_service().view_screenshot_summary())
    _refresh_phase_context()
    _refresh_pending_actions()
    _refresh_action_history()
    _refresh_workbench_context()
    _append_output(
        "Cleared local VibeCAD session: "
        f"{result['pending_count']} pending, {result['history_count']} history."
    )


def _assistant_dock_preferences():
    return App.ParamGet(_ASSISTANT_DOCK_PREF_GROUP)


def _assistant_dock_should_auto_open() -> bool:
    return True


def show_assistant_for_active_workbench() -> None:
    _show_panel()


def _refresh_assistant_for_document_change() -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel") if main_window else None
    if dock is None or not _assistant_panel_is_built(dock):
        return
    _render_saved_conversation(dock)
    _refresh_assistant_panel_state(dock)


def _schedule_assistant_document_refresh() -> None:
    try:
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, _refresh_assistant_for_document_change)
    except Exception:
        _refresh_assistant_for_document_change()


def _snapshot_active_document_conversation(doc: Any) -> None:
    if doc is None:
        return
    try:
        active_doc = App.ActiveDocument
    except Exception:
        active_doc = None
    if active_doc is not doc and getattr(active_doc, "Name", None) != getattr(doc, "Name", None):
        return
    try:
        history = get_service().conversation_history()
    except Exception as exc:
        _warn(f"VibeCAD conversation snapshot failed: {exc}")
        return
    conversation = history.get("conversation", [])
    if isinstance(conversation, list) and conversation:
        _document_save_conversations[str(getattr(doc, "Name", ""))] = [
            dict(item) for item in conversation if isinstance(item, dict)
        ]


def _move_saved_document_conversation(doc: Any, filepath: str) -> None:
    doc_name = str(getattr(doc, "Name", ""))
    conversation = _document_save_conversations.pop(doc_name, None)
    if not conversation:
        try:
            history = get_service().conversation_history()
            current = history.get("conversation", [])
            conversation = [dict(item) for item in current if isinstance(item, dict)]
        except Exception:
            conversation = []
    if not conversation:
        return
    try:
        get_service().write_conversation_for_document_file(filepath, conversation)
    except Exception as exc:
        _warn(f"VibeCAD saved-document conversation write failed: {exc}")


class _VibeCADDocumentObserver:
    def slotCreatedDocument(self, doc) -> None:
        _schedule_assistant_document_refresh()

    def slotActivateDocument(self, doc) -> None:
        _schedule_assistant_document_refresh()

    def slotStartSaveDocument(self, doc, filepath) -> None:
        _snapshot_active_document_conversation(doc)

    def slotFinishSaveDocument(self, doc, filepath) -> None:
        _move_saved_document_conversation(doc, str(filepath))
        _schedule_assistant_document_refresh()

    def slotDeletedDocument(self, doc) -> None:
        _document_save_conversations.pop(str(getattr(doc, "Name", "")), None)
        _schedule_assistant_document_refresh()


def _connect_document_observer() -> None:
    global _document_observer_connected, _document_observer
    if _document_observer_connected:
        return
    try:
        _document_observer = _VibeCADDocumentObserver()
        App.addDocumentObserver(_document_observer)
        _document_observer_connected = True
    except Exception as exc:
        _warn(f"VibeCAD document observer failed: {exc}")


def _save_assistant_splitter_sizes(splitter) -> None:
    try:
        sizes = [int(size) for size in splitter.sizes()]
    except Exception:
        return
    if len(sizes) != 3 or sum(sizes) <= 0:
        return
    _assistant_dock_preferences().SetString(
        "ConversationSplitterSizes",
        " ".join(str(size) for size in sizes),
    )


def _restore_assistant_splitter_sizes(splitter) -> None:
    value = _assistant_dock_preferences().GetString("ConversationSplitterSizes", "")
    try:
        sizes = [int(part) for part in value.split()]
    except Exception:
        sizes = []
    if len(sizes) != 3 or sum(sizes) <= 0:
        sizes = [420, 120, 110]
    splitter.setSizes(sizes)


def _assistant_dock_area_name(area) -> str:
    try:
        from PySide import QtCore
    except Exception:
        return "right"

    if area == QtCore.Qt.LeftDockWidgetArea:
        return "left"
    if area == QtCore.Qt.TopDockWidgetArea:
        return "top"
    if area == QtCore.Qt.BottomDockWidgetArea:
        return "bottom"
    return "right"


def _assistant_dock_area_from_name(name: str):
    from PySide import QtCore

    clean = str(name or "").strip().lower()
    if clean == "left":
        return QtCore.Qt.LeftDockWidgetArea
    if clean == "top":
        return QtCore.Qt.TopDockWidgetArea
    if clean == "bottom":
        return QtCore.Qt.BottomDockWidgetArea
    return QtCore.Qt.RightDockWidgetArea


def _parse_assistant_dock_rect(value: str):
    from PySide import QtCore

    try:
        x, y, width, height = [int(part) for part in str(value or "").split()]
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return QtCore.QRect(x, y, width, height)


def _available_assistant_screen_geometry():
    from PySide import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance()
    rect = None
    screens = app.screens() if app is not None and hasattr(app, "screens") else []
    for screen in screens:
        available = screen.availableGeometry()
        rect = QtCore.QRect(available) if rect is None else rect.united(available)
    if rect is not None and rect.isValid():
        return rect
    if app is not None and hasattr(app, "desktop"):
        desktop = app.desktop()
        if desktop is not None:
            return desktop.availableGeometry()
    return QtCore.QRect(0, 0, 1024, 768)


def _clamp_assistant_dock_rect_to_screens(rect):
    from PySide import QtCore

    available = _available_assistant_screen_geometry()
    available_width = max(1, available.width())
    available_height = max(1, available.height())
    minimum_width = min(300, available_width)
    minimum_height = min(240, available_height)
    width = min(max(rect.width(), minimum_width), available_width)
    height = min(max(rect.height(), minimum_height), available_height)
    max_x = available.x() + available.width() - width
    max_y = available.y() + available.height() - height
    x = available.x() if max_x < available.x() else min(max(rect.x(), available.x()), max_x)
    y = available.y() if max_y < available.y() else min(max(rect.y(), available.y()), max_y)
    return QtCore.QRect(x, y, width, height)


def _clamp_assistant_dock_to_screens(dock) -> None:
    if dock is None or not dock.isFloating():
        return
    rect = _clamp_assistant_dock_rect_to_screens(dock.geometry())
    if rect != dock.geometry():
        dock.setGeometry(rect)


def _assistant_docked_side_width_limit(main_window) -> int:
    try:
        window_width = int(main_window.width())
    except Exception:
        window_width = 1600
    if window_width <= 0:
        window_width = 1600
    return max(420, min(680, int(window_width * 0.38)))


def _assistant_docked_area_is_side(area) -> bool:
    try:
        from PySide import QtCore
    except Exception:
        return False
    return area in (QtCore.Qt.LeftDockWidgetArea, QtCore.Qt.RightDockWidgetArea)


def _apply_assistant_dock_size_limits(dock, main_window) -> None:
    if dock is None or main_window is None:
        return
    try:
        area = main_window.dockWidgetArea(dock)
    except Exception:
        area = None
    dock.setMinimumWidth(300)
    if bool(dock.isFloating()) or not _assistant_docked_area_is_side(area):
        dock.setMaximumWidth(16777215)
        return
    dock.setMaximumWidth(_assistant_docked_side_width_limit(main_window))


def _normalize_assistant_dock_size(dock, main_window) -> None:
    if dock is None or main_window is None or bool(dock.isFloating()):
        return
    try:
        from PySide import QtCore
    except Exception:
        return
    area = main_window.dockWidgetArea(dock)
    if not _assistant_docked_area_is_side(area):
        return
    limit = _assistant_docked_side_width_limit(main_window)
    if int(dock.width()) <= limit:
        return
    try:
        main_window.resizeDocks([dock], [limit], QtCore.Qt.Horizontal)
    except Exception:
        pass


def _save_assistant_dock_placement(dock, main_window=None) -> None:
    if dock is None or _assistant_dock_restoring:
        return

    if main_window is None:
        main_window = Gui.getMainWindow()
    if main_window is None:
        return

    prefs = _assistant_dock_preferences()
    prefs.SetBool("HasPlacement", True)
    prefs.SetBool("Floating", bool(dock.isFloating()))
    prefs.SetBool("Visible", bool(dock.isVisible()))
    area = main_window.dockWidgetArea(dock)
    prefs.SetString("Area", _assistant_dock_area_name(area))
    width = int(dock.width())
    if not dock.isFloating() and _assistant_docked_area_is_side(area):
        width = min(width, _assistant_docked_side_width_limit(main_window))
    prefs.SetInt("Width", width)
    prefs.SetInt("Height", int(dock.height()))
    rect = dock.geometry()
    if dock.isFloating():
        rect = _clamp_assistant_dock_rect_to_screens(rect)
    prefs.SetString(
        "Geometry",
        f"{rect.x()} {rect.y()} {rect.width()} {rect.height()}",
    )


def _restore_assistant_dock_from_preferences(dock, main_window) -> bool:
    try:
        from PySide import QtCore
    except Exception:
        return False

    prefs = _assistant_dock_preferences()
    if not prefs.GetBool("HasPlacement", False):
        return False

    area = _assistant_dock_area_from_name(prefs.GetString("Area", "right"))
    main_window.addDockWidget(area, dock)
    _apply_assistant_dock_size_limits(dock, main_window)
    if prefs.GetBool("Floating", False):
        dock.setFloating(True)
        _apply_assistant_dock_size_limits(dock, main_window)
        rect = _parse_assistant_dock_rect(prefs.GetString("Geometry", ""))
        if rect is not None:
            dock.setGeometry(_clamp_assistant_dock_rect_to_screens(rect))
        return True

    dock.setFloating(False)
    size = prefs.GetInt("Height", 360) if area in (
        QtCore.Qt.TopDockWidgetArea,
        QtCore.Qt.BottomDockWidgetArea,
    ) else prefs.GetInt("Width", 360)
    if _assistant_docked_area_is_side(area):
        size = min(size, _assistant_docked_side_width_limit(main_window))
    orientation = QtCore.Qt.Vertical if area in (
        QtCore.Qt.TopDockWidgetArea,
        QtCore.Qt.BottomDockWidgetArea,
    ) else QtCore.Qt.Horizontal
    try:
        main_window.resizeDocks([dock], [max(240, size)], orientation)
    except Exception:
        pass
    _normalize_assistant_dock_size(dock, main_window)
    return True


def _place_assistant_dock_default(dock, main_window) -> None:
    try:
        from PySide import QtCore
    except Exception:
        return

    main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    _apply_assistant_dock_size_limits(dock, main_window)
    try:
        main_window.resizeDocks([dock], [360], QtCore.Qt.Horizontal)
    except Exception:
        pass


def _restore_assistant_dock_placement(dock, main_window) -> None:
    global _assistant_dock_restoring

    _assistant_dock_restoring = True
    try:
        restored_by_main_window = False
        try:
            restored_by_main_window = bool(main_window.restoreDockWidget(dock))
        except Exception:
            restored_by_main_window = False

        if restored_by_main_window:
            _clamp_assistant_dock_to_screens(dock)
            _apply_assistant_dock_size_limits(dock, main_window)
            _normalize_assistant_dock_size(dock, main_window)
            return
        try:
            if _restore_assistant_dock_from_preferences(dock, main_window):
                return
        except Exception as exc:
            _warn(f"VibeCAD assistant dock placement restore failed: {exc}")
        try:
            _place_assistant_dock_default(dock, main_window)
        except Exception as exc:
            _warn(f"VibeCAD assistant default dock placement failed: {exc}")
    finally:
        _assistant_dock_restoring = False


def _handle_assistant_screen_change() -> None:
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        return

    def clamp_and_save() -> None:
        main_window = Gui.getMainWindow()
        if main_window is None:
            return
        dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
        if dock is None:
            return
        _clamp_assistant_dock_to_screens(dock)
        _apply_assistant_dock_size_limits(dock, main_window)
        _normalize_assistant_dock_size(dock, main_window)
        _save_assistant_dock_placement(dock, main_window)

    QtCore.QTimer.singleShot(0, clamp_and_save)


def _connect_assistant_screen_events() -> None:
    global _assistant_screen_events_connected, _assistant_screen_change_handler
    if _assistant_screen_events_connected:
        return
    try:
        from PySide import QtWidgets
    except Exception:
        return

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    _assistant_screen_change_handler = lambda *args: _handle_assistant_screen_change()
    for signal_name in ("screenAdded", "screenRemoved", "primaryScreenChanged"):
        signal = getattr(app, signal_name, None)
        if signal is not None:
            try:
                signal.connect(_assistant_screen_change_handler)
            except Exception:
                pass
    _assistant_screen_events_connected = True


def _connect_assistant_dock_placement(dock, main_window) -> None:
    if dock.property("VibeCADDockPlacementConnected"):
        return
    try:
        from PySide import QtCore
    except Exception:
        return

    class AssistantDockEventFilter(QtCore.QObject):
        def eventFilter(self, watched, event):
            event_type = event.type()
            if event_type in {
                QtCore.QEvent.Move,
                QtCore.QEvent.Hide,
                QtCore.QEvent.Close,
            }:
                _save_assistant_dock_placement(watched, main_window)
            return False

    try:
        event_filter = AssistantDockEventFilter(dock)
        dock.installEventFilter(event_filter)
        dock._vibecad_dock_event_filter = event_filter
        dock.dockLocationChanged.connect(
            lambda area: (
                _apply_assistant_dock_size_limits(dock, main_window),
                _normalize_assistant_dock_size(dock, main_window),
                _save_assistant_dock_placement(dock, main_window),
            )
        )
        dock.topLevelChanged.connect(
            lambda floating: (
                _apply_assistant_dock_size_limits(dock, main_window),
                _normalize_assistant_dock_size(dock, main_window),
                _save_assistant_dock_placement(dock, main_window),
            )
        )
        dock.setProperty("VibeCADDockPlacementConnected", True)
    except Exception as exc:
        _warn(f"VibeCAD assistant dock placement observer failed: {exc}")


def _configure_assistant_window(dock, main_window) -> None:
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        return

    dock.setAllowedAreas(
        QtCore.Qt.LeftDockWidgetArea
        | QtCore.Qt.RightDockWidgetArea
        | QtCore.Qt.TopDockWidgetArea
        | QtCore.Qt.BottomDockWidgetArea
    )
    dock.setFeatures(
        QtWidgets.QDockWidget.DockWidgetClosable
        | QtWidgets.QDockWidget.DockWidgetMovable
        | QtWidgets.QDockWidget.DockWidgetFloatable
    )
    _apply_assistant_dock_size_limits(dock, main_window)


def _assistant_panel_is_built(dock) -> bool:
    try:
        from PySide import QtWidgets
    except Exception:
        return False
    return (
        dock is not None
        and dock.widget() is not None
        and dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput") is not None
        and dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADThinking") is not None
        and dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt") is not None
    )


def _refresh_assistant_panel_state(dock) -> None:
    try:
        _refresh_phase_context()
        _refresh_workbench_context()
        _refresh_pending_actions()
        _refresh_action_history()
        _render_assistant_run_state(dock)
    except Exception as exc:
        _warn(f"VibeCAD assistant panel refresh failed: {exc}")


def _show_existing_assistant_panel(dock, main_window, text: str = "") -> None:
    try:
        from PySide import QtWidgets
    except Exception:
        return

    try:
        _configure_assistant_window(dock, main_window)
        _normalize_assistant_dock_size(dock, main_window)
    except Exception as exc:
        _warn(f"VibeCAD assistant dock configuration failed: {exc}")
    dock.show()
    dock.raise_()
    _pump_assistant_ui_events()
    _normalize_assistant_dock_size(dock, main_window)
    if text:
        output = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput")
        if output is not None:
            output.setPlainText(text)
    else:
        _render_saved_conversation(dock)
    _connect_assistant_dock_placement(dock, main_window)
    _connect_assistant_screen_events()
    _refresh_assistant_panel_state(dock)


def _refresh_existing_assistant_panel(dock) -> None:
    if not _assistant_panel_is_built(dock):
        return
    _refresh_assistant_panel_state(dock)


def _find_combo_or_task_dock(main_window):
    try:
        from PySide import QtWidgets
    except Exception:
        return None

    preferred_names = {
        "Combo View",
        "ComboView",
        "Task View",
        "TaskView",
        "Tasks",
        "Tree view",
        "TreeView",
    }
    docks = main_window.findChildren(QtWidgets.QDockWidget)
    for dock in docks:
        title = str(dock.windowTitle() or "")
        name = str(dock.objectName() or "")
        if title in preferred_names or name in preferred_names:
            return dock
    for dock in docks:
        title = str(dock.windowTitle() or "").lower()
        name = str(dock.objectName() or "").lower()
        if "combo" in title or "combo" in name or "task" in title or "task" in name:
            return dock
    return None


def _dock_is_in_overlay(dock) -> bool:
    try:
        parent = dock.parentWidget()
        while parent is not None:
            if "Overlay" in parent.metaObject().className():
                return True
            parent = parent.parentWidget()
    except Exception:
        return False
    return False


def _try_enable_freecad_overlay(dock) -> bool:
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        return False

    dock.show()
    dock.raise_()
    dock.setFocus(QtCore.Qt.OtherFocusReason)
    QtWidgets.QApplication.processEvents()
    title = dock.titleBarWidget()
    candidates = []
    if title is not None:
        candidates.extend(title.findChildren(QtCore.QObject))
    candidates.extend(dock.findChildren(QtCore.QObject))
    for item in candidates:
        action = item if hasattr(item, "trigger") else None
        if action is None:
            continue
        try:
            if str(action.data()) == "OBTN Overlay":
                action.trigger()
                QtWidgets.QApplication.processEvents()
                return _dock_is_in_overlay(dock)
        except Exception:
            continue
    return False


def _show_panel(text: str = "") -> None:
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        _print(text or "VibeCAD assistant panel requires Qt.")
        return

    main_window = Gui.getMainWindow()
    dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    add_dock = dock is None
    if dock is not None and _assistant_panel_is_built(dock):
        _show_existing_assistant_panel(dock, main_window, text)
        return
    if dock is None:
        dock = QtWidgets.QDockWidget("VibeCAD", main_window)
        dock.setObjectName("VibeCADAssistantPanel")
    existing_widget = dock.widget()
    if existing_widget is not None:
        existing_widget.setParent(None)
        existing_widget.deleteLater()
    widget = QtWidgets.QWidget(dock)
    widget.setObjectName("VibeCADAssistantRootConversation")
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)

    def configure_text_box(
        edit,
        height: int,
        *,
        read_only: bool = True,
        metadata: bool = False,
    ) -> None:
        edit.setReadOnly(read_only)
        edit.setMinimumHeight(height)
        edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        if metadata:
            edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            edit.setFocusPolicy(QtCore.Qt.NoFocus)

    output = QtWidgets.QPlainTextEdit(widget)
    output.setObjectName("VibeCADOutput")
    output.setReadOnly(True)
    output.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
    output.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    output.setMinimumHeight(56)
    output.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding,
        QtWidgets.QSizePolicy.Expanding,
    )
    output.setPlainText("")
    thinking = QtWidgets.QPlainTextEdit(widget)
    thinking.setObjectName("VibeCADThinking")
    thinking.setReadOnly(True)
    thinking.setMinimumHeight(44)
    thinking.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
    thinking.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    thinking.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding,
        QtWidgets.QSizePolicy.Expanding,
    )
    thinking.setPlainText(_IDLE_THINKING_TEXT)
    thinking.setVisible(False)
    commands = QtWidgets.QPlainTextEdit(widget)
    commands.setObjectName("VibeCADWorkbenchCommands")
    commands.setReadOnly(True)
    commands.setFixedHeight(92)
    templates = QtWidgets.QPlainTextEdit(widget)
    templates.setObjectName("VibeCADObjectTemplates")
    templates.setReadOnly(True)
    templates.setFixedHeight(64)
    objects = QtWidgets.QPlainTextEdit(widget)
    objects.setObjectName("VibeCADWorkbenchObjects")
    objects.setReadOnly(True)
    objects.setFixedHeight(72)
    provider_tools = QtWidgets.QPlainTextEdit(widget)
    provider_tools.setObjectName("VibeCADProviderTools")
    provider_tools.setReadOnly(True)
    provider_tools.setFixedHeight(92)
    tool_trace = QtWidgets.QPlainTextEdit(widget)
    tool_trace.setObjectName("VibeCADToolTrace")
    tool_trace.setReadOnly(True)
    tool_trace.setFixedHeight(76)
    report_errors = QtWidgets.QPlainTextEdit(widget)
    report_errors.setObjectName("VibeCADReportErrors")
    report_errors.setReadOnly(True)
    report_errors.setFixedHeight(58)
    part = QtWidgets.QPlainTextEdit(widget)
    part.setObjectName("VibeCADPartContext")
    part.setReadOnly(True)
    part.setFixedHeight(64)
    mesh = QtWidgets.QPlainTextEdit(widget)
    mesh.setObjectName("VibeCADMeshContext")
    mesh.setReadOnly(True)
    mesh.setFixedHeight(64)
    points = QtWidgets.QPlainTextEdit(widget)
    points.setObjectName("VibeCADPointsContext")
    points.setReadOnly(True)
    points.setFixedHeight(64)
    material = QtWidgets.QPlainTextEdit(widget)
    material.setObjectName("VibeCADMaterialContext")
    material.setReadOnly(True)
    material.setFixedHeight(64)
    sketcher = QtWidgets.QPlainTextEdit(widget)
    sketcher.setObjectName("VibeCADSketcherContext")
    sketcher.setReadOnly(True)
    sketcher.setFixedHeight(52)
    spreadsheet = QtWidgets.QPlainTextEdit(widget)
    spreadsheet.setObjectName("VibeCADSpreadsheetContext")
    spreadsheet.setReadOnly(True)
    spreadsheet.setFixedHeight(52)
    draft = QtWidgets.QPlainTextEdit(widget)
    draft.setObjectName("VibeCADDraftContext")
    draft.setReadOnly(True)
    draft.setFixedHeight(64)
    partdesign = QtWidgets.QPlainTextEdit(widget)
    partdesign.setObjectName("VibeCADPartDesignContext")
    partdesign.setReadOnly(True)
    partdesign.setFixedHeight(64)
    techdraw = QtWidgets.QPlainTextEdit(widget)
    techdraw.setObjectName("VibeCADTechDrawContext")
    techdraw.setReadOnly(True)
    techdraw.setFixedHeight(64)
    fem = QtWidgets.QPlainTextEdit(widget)
    fem.setObjectName("VibeCADFemContext")
    fem.setReadOnly(True)
    fem.setFixedHeight(64)
    cam = QtWidgets.QPlainTextEdit(widget)
    cam.setObjectName("VibeCADCamContext")
    cam.setReadOnly(True)
    cam.setFixedHeight(64)
    bim = QtWidgets.QPlainTextEdit(widget)
    bim.setObjectName("VibeCADBimContext")
    bim.setReadOnly(True)
    bim.setFixedHeight(64)
    assembly = QtWidgets.QPlainTextEdit(widget)
    assembly.setObjectName("VibeCADAssemblyContext")
    assembly.setReadOnly(True)
    assembly.setFixedHeight(64)
    inspection = QtWidgets.QPlainTextEdit(widget)
    inspection.setObjectName("VibeCADInspectionContext")
    inspection.setReadOnly(True)
    inspection.setFixedHeight(64)
    openscad = QtWidgets.QPlainTextEdit(widget)
    openscad.setObjectName("VibeCADOpenSCADContext")
    openscad.setReadOnly(True)
    openscad.setFixedHeight(64)
    surface = QtWidgets.QPlainTextEdit(widget)
    surface.setObjectName("VibeCADSurfaceContext")
    surface.setReadOnly(True)
    surface.setFixedHeight(64)
    reen = QtWidgets.QPlainTextEdit(widget)
    reen.setObjectName("VibeCADReverseEngineeringContext")
    reen.setReadOnly(True)
    reen.setFixedHeight(64)
    robot = QtWidgets.QPlainTextEdit(widget)
    robot.setObjectName("VibeCADRobotContext")
    robot.setReadOnly(True)
    robot.setFixedHeight(64)
    meshpart = QtWidgets.QPlainTextEdit(widget)
    meshpart.setObjectName("VibeCADMeshPartContext")
    meshpart.setReadOnly(True)
    meshpart.setFixedHeight(64)
    for internal_widget in (
        commands,
        templates,
        objects,
        provider_tools,
        tool_trace,
        report_errors,
        part,
        mesh,
        points,
        material,
        sketcher,
        spreadsheet,
        draft,
        partdesign,
        techdraw,
        fem,
        cam,
        bim,
        assembly,
        inspection,
        openscad,
        surface,
        reen,
        robot,
        meshpart,
    ):
        internal_widget.setVisible(False)
    prompt = QtWidgets.QPlainTextEdit(widget)
    prompt.setObjectName("VibeCADPrompt")
    prompt.setPlaceholderText("Message VibeCAD...")
    configure_text_box(prompt, 48, read_only=False)
    run_status = QtWidgets.QLabel("Ready.", widget)
    run_status.setObjectName("VibeCADRunStatus")
    run_status.setVisible(False)
    screenshot_status = QtWidgets.QLabel(widget)
    screenshot_status.setObjectName("VibeCADScreenshotStatus")
    screenshot_status.setVisible(False)
    mode_label = QtWidgets.QLabel("Mode", widget)
    mode_label.setObjectName("VibeCADModeLabel")
    mode_selector = QtWidgets.QComboBox(widget)
    mode_selector.setObjectName("VibeCADModeSelector")
    mode_selector.setMinimumWidth(132)
    mode_selector.setMaximumWidth(180)
    for phase in PHASE_ORDER:
        mode_selector.addItem(_phase_label(phase), phase)
    mode_selector.currentIndexChanged.connect(_mode_changed_from_panel)
    capture_view_button = QtWidgets.QPushButton("Attach View", widget)
    capture_view_button.setObjectName("VibeCADCaptureView")
    capture_view_button.clicked.connect(_capture_view_from_panel)
    control_bar = QtWidgets.QWidget(widget)
    control_bar.setObjectName("VibeCADControlBar")
    controls = QtWidgets.QHBoxLayout(control_bar)
    controls.setContentsMargins(0, 0, 0, 0)
    controls.setSpacing(6)
    run_button = QtWidgets.QPushButton("Send", widget)
    run_button.setObjectName("VibeCADRunPrompt")
    run_button.clicked.connect(_run_prompt_from_panel)
    stop_button = QtWidgets.QPushButton("Stop", widget)
    stop_button.setObjectName("VibeCADStopPrompt")
    stop_button.setEnabled(False)
    stop_button.clicked.connect(_stop_prompt_from_panel)
    controls.addWidget(mode_label)
    controls.addWidget(mode_selector)
    controls.addWidget(capture_view_button)
    controls.addStretch(1)
    controls.addWidget(run_button)
    controls.addWidget(stop_button)
    conversation_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, widget)
    conversation_splitter.setObjectName("VibeCADConversationSplitter")
    conversation_splitter.setChildrenCollapsible(False)
    conversation_splitter.setHandleWidth(5)
    conversation_splitter.addWidget(output)
    conversation_splitter.addWidget(thinking)
    conversation_splitter.addWidget(prompt)
    conversation_splitter.splitterMoved.connect(
        lambda pos, index: _save_assistant_splitter_sizes(conversation_splitter)
    )
    _restore_assistant_splitter_sizes(conversation_splitter)
    layout.addWidget(conversation_splitter, 1)
    layout.addWidget(screenshot_status)
    layout.addWidget(run_status)
    layout.addWidget(control_bar)
    dock.setWidget(widget)
    try:
        _configure_assistant_window(dock, main_window)
        _normalize_assistant_dock_size(dock, main_window)
    except Exception as exc:
        _warn(f"VibeCAD assistant dock configuration failed: {exc}")
    if add_dock:
        _restore_assistant_dock_placement(dock, main_window)
    _normalize_assistant_dock_size(dock, main_window)
    dock.show()
    dock.raise_()
    _pump_assistant_ui_events()
    _normalize_assistant_dock_size(dock, main_window)
    try:
        _save_assistant_dock_placement(dock, main_window)
    except Exception as exc:
        _warn(f"VibeCAD assistant dock placement save failed: {exc}")
    _connect_assistant_dock_placement(dock, main_window)
    _connect_assistant_screen_events()

    output = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput")
    if output is not None and text:
        output.setPlainText(text)
    elif output is not None:
        _render_saved_conversation(dock)
    _refresh_assistant_panel_state(dock)


def _on_workbench_activated(workbench_name: str) -> None:
    if get_tool_pack(str(workbench_name)) is None:
        return
    try:
        from PySide import QtCore, QtWidgets
    except Exception:
        return

    def refresh_existing_panel() -> None:
        main_window = Gui.getMainWindow()
        if main_window is None:
            return
        dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
        if dock is not None:
            _refresh_existing_assistant_panel(dock)
            return
        if _assistant_dock_should_auto_open():
            _show_panel()

    QtCore.QTimer.singleShot(0, refresh_existing_panel)


def _connect_workbench_activation() -> None:
    global _workbench_activation_connected
    if _workbench_activation_connected:
        return
    try:
        main_window = Gui.getMainWindow()
        main_window.workbenchActivated.connect(_on_workbench_activated)
        _workbench_activation_connected = True
    except Exception as exc:
        App.Console.PrintWarning(
            f"VibeCAD AI assistant could not watch workbench activation: {exc}\n"
        )


def _wrap_workbench_activation(workbench: Any) -> None:
    if getattr(workbench, "__VibeCADActivatedWrapped__", False):
        return
    original = getattr(workbench, "Activated", None)

    def _activated_with_vibecad(*args: Any, **kwargs: Any) -> Any:
        result = None
        if callable(original):
            result = original(*args, **kwargs)
        try:
            active = get_service().active_workbench_name()
            if active:
                _on_workbench_activated(active)
        except Exception as exc:
            App.Console.PrintWarning(
                f"VibeCAD assistant could not open after workbench activation: {exc}\n"
            )
        return result

    setattr(workbench, "__VibeCADOriginalActivated__", original)
    setattr(workbench, "Activated", _activated_with_vibecad)
    setattr(workbench, "__VibeCADActivatedWrapped__", True)


class _BaseCommand:
    name = "VibeCAD"
    menu_text = "VibeCAD"
    tooltip = "VibeCAD AI command"

    def GetResources(self) -> dict[str, Any]:
        return {
            "Pixmap": "applications-python",
            "MenuText": self.menu_text,
            "ToolTip": self.tooltip,
        }

    def IsActive(self) -> bool:
        return True


class AskAICommand(_BaseCommand):
    menu_text = "Ask AI"
    tooltip = "Ask VibeCAD in the current workbench context"

    def Activated(self) -> None:
        service = get_service()
        response = run_prompt("Summarize the current FreeCAD context.", service=service)
        _show_panel(f"[{response.provider}] {response.final_output}")


class ExplainSelectionCommand(_BaseCommand):
    menu_text = "Explain Selection"
    tooltip = "Explain the current selection using VibeCAD context tools"

    def Activated(self) -> None:
        selection = get_service().selection_summary()
        _show_panel(f"Selection context:\n{selection}")


class OpenAssistantCommand(_BaseCommand):
    menu_text = "Open AI Assistant"
    tooltip = "Open the VibeCAD assistant panel for the active workbench"

    def Activated(self) -> None:
        _show_panel()


class OpenPreferencesCommand(_BaseCommand):
    menu_text = "AI Preferences"
    tooltip = "Open VibeCAD preferences"

    def Activated(self) -> None:
        ensure_preferences_registered()
        try:
            Gui.showPreferencesByName("VibeCAD", "VibeCAD")
        except Exception:
            try:
                Gui.showPreferences("VibeCAD", 0)
            except Exception as exc:
                _show_panel(f"VibeCAD preferences could not be opened: {exc}")


class AuthStatusCommand(_BaseCommand):
    menu_text = "AI Auth Status"
    tooltip = "Show VibeCAD authentication status"

    def Activated(self) -> None:
        auth = get_service().auth_state()
        source = f" from {auth.source}" if auth.source else ""
        _show_panel(f"VibeCAD auth status: {auth.status.value}{source}\n{auth.message}")


def ensure_preferences_registered() -> None:
    global _preferences_registered
    if _preferences_registered:
        return
    import VibeCADPreferences

    Gui.addIconPath(str(Path(__file__).resolve().parent))
    Gui.addPreferencePage(VibeCADPreferences.PreferencesPage, "VibeCAD")
    _preferences_registered = True


def ensure_commands_registered() -> None:
    global _commands_registered, _workbench_manipulator
    ensure_preferences_registered()
    _connect_document_observer()
    if _commands_registered:
        _connect_workbench_activation()
        return
    Gui.addCommand("VibeCAD_AskAI", AskAICommand())
    Gui.addCommand("VibeCAD_ExplainSelection", ExplainSelectionCommand())
    Gui.addCommand("VibeCAD_OpenAssistant", OpenAssistantCommand())
    Gui.addCommand("VibeCAD_OpenPreferences", OpenPreferencesCommand())
    Gui.addCommand("VibeCAD_AuthStatus", AuthStatusCommand())
    _workbench_manipulator = _WorkbenchManipulator()
    Gui.addWorkbenchManipulator(_workbench_manipulator)
    _connect_workbench_activation()
    _commands_registered = True


def register_ai_commands_for_workbench(workbench: Any, workbench_name: str) -> None:
    """Attach shared VibeCAD commands to an existing workbench.

    This does not create or register a VibeCAD workbench. It adds native AI
    affordances to the workbench that called it.
    """

    ensure_commands_registered()
    _wrap_workbench_activation(workbench)
    native_workbench = getattr(workbench, "__Workbench__", None)
    if native_workbench is None:
        return

    try:
        native_workbench.appendToolbar("AI", COMMANDS)
        native_workbench.appendMenu(["AI"], COMMANDS)
        native_workbench.appendContextMenu("VibeCAD", CONTEXT_COMMANDS)
    except Exception as exc:
        App.Console.PrintWarning(
            f"VibeCAD could not attach AI UI to {workbench_name}: {exc}\n"
        )
