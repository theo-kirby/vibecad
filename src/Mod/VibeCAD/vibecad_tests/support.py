# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared fakes and fixtures for the VibeCAD test suite."""

import json
import os
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

import VibeCADProject
from VibeCADCore import VibeCADService
from VibeCADPreferences import (
    VibeCADSettings,
    load_settings,
    save_settings,
)
from VibeCADProject import VibeCADProjectStore


_OFFSCREEN_QAPP = None


def _ensure_offscreen_qapplication():
    """Return a usable QApplication, creating an offscreen one if needed."""
    global _OFFSCREEN_QAPP
    try:
        from PySide import QtWidgets
    except Exception:
        return None
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        _OFFSCREEN_QAPP = QtWidgets.QApplication(["TestVibeCAD"])
    except Exception:
        return None
    return _OFFSCREEN_QAPP


def _repo_tool_script(name: str) -> Path:
    candidates = [
        Path.cwd() / "tools" / name,
        Path.cwd().parent.parent / "tools" / name,
        Path(__file__).resolve().parents[4] / "tools" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _gui_workbench_api_available() -> bool:
    try:
        import FreeCADGui as Gui

        return hasattr(Gui, "activateWorkbench") and hasattr(Gui, "listWorkbenches")
    except Exception:
        return False


def _attach_temp_project_store(service: VibeCADService, root: Path, label: str = "Unit Test Project"):
    service._project_store = VibeCADProjectStore(  # noqa: SLF001 - test fixture
        f"unit-{time.time_ns()}",
        index_path=root / "index.sqlite",
    )
    original = VibeCADProject._active_document_info
    VibeCADProject._active_document_info = lambda: {
        "document": label.replace(" ", ""),
        "label": label,
        "file_path": str(root / f"{label.replace(' ', '_')}.FCStd"),
        "saved": True,
    }
    return original


@contextmanager
def _temporary_design_project(
    service: VibeCADService,
    label: str = "Unit Test Project",
):
    with tempfile.TemporaryDirectory() as tmp:
        original = _attach_temp_project_store(service, Path(tmp), label)
        try:
            yield
        finally:
            VibeCADProject._active_document_info = original


@contextmanager
def _temporary_vibecad_home():
    """Scope every VibeCAD data-dir write to a throwaway VIBECAD_HOME."""
    old_home = os.environ.get("VIBECAD_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "vibecad-home"
        os.environ["VIBECAD_HOME"] = str(home)
        try:
            yield home
        finally:
            if old_home is None:
                os.environ.pop("VIBECAD_HOME", None)
            else:
                os.environ["VIBECAD_HOME"] = old_home


@contextmanager
def _fake_active_document(info: dict):
    """Pretend the given document info is the active FreeCAD document."""
    original = VibeCADProject._active_document_info
    VibeCADProject._active_document_info = lambda: dict(info)
    try:
        yield
    finally:
        VibeCADProject._active_document_info = original


class FakeKeyringModule:
    def __init__(self) -> None:
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


class FakeHTTPResponse:
    def __init__(self, status=200):
        self.status = status
        self.closed = False

    def read(self, _limit=-1):
        return b"{}"

    def close(self):
        self.closed = True


class FakeJSONResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload

    def read(self, _limit=-1):
        return json.dumps(self._payload).encode("utf-8")

    def close(self):
        pass


def _fake_anthropic_module(
    tool_function_name: str,
    *,
    final_text: str = "All done.",
    always_tool_use: bool = False,
):
    """Build a stand-in ``anthropic`` module driving one tool round-trip.

    The module is installed into ``sys.modules`` before forking so the child
    process imports it instead of the real SDK. First call returns a
    ``tool_use`` block for ``tool_function_name``; the next call verifies the
    tool_result message and finishes with ``end_turn``.
    """

    module = types.ModuleType("anthropic")

    class _FakeStream:
        """Context manager mimicking ``client.messages.stream(...)``."""

        def __init__(self, final_message):
            self._final_message = final_message

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def get_final_message(self):
            return self._final_message

    class _FakeMessages:
        def __init__(self):
            self.calls = 0

        def stream(self, *, messages, model, max_tokens, system, tools, **_kwargs):
            return _FakeStream(
                self.create(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tools,
                    **_kwargs,
                )
            )

        def create(self, *, messages, model, max_tokens, system, tools, **_kwargs):
            self.calls += 1
            if always_tool_use or self.calls == 1:
                block = types.SimpleNamespace(
                    type="tool_use",
                    name=tool_function_name,
                    id=f"toolu_test_{self.calls}",
                    input={},
                )
                return types.SimpleNamespace(
                    content=[block], stop_reason="tool_use"
                )
            last = messages[-1]
            if last["role"] != "user" or last["content"][0]["type"] != "tool_result":
                raise RuntimeError(
                    "Expected a tool_result message before the final turn."
                )
            result_payload = json.loads(last["content"][0]["content"])
            if not result_payload.get("ok"):
                raise RuntimeError(f"Tool bridge returned failure: {result_payload}")
            text_block = types.SimpleNamespace(type="text", text=final_text)
            return types.SimpleNamespace(content=[text_block], stop_reason="end_turn")

    class _FakeAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _FakeMessages()

    module.Anthropic = _FakeAnthropic
    return module


class SettingsSnapshotTestCase(unittest.TestCase):
    """Base class that snapshots and restores VibeCAD settings around each test."""

    def setUp(self):
        self._old_settings = load_settings()
        save_settings(
            VibeCADSettings(
                use_online_provider=self._old_settings.use_online_provider,
                model=self._old_settings.model,
                dotenv_path=self._old_settings.dotenv_path,
                reasoning_effort=self._old_settings.reasoning_effort,
                provider=self._old_settings.provider,
                anthropic_model=self._old_settings.anthropic_model,
                enable_build_script=self._old_settings.enable_build_script,
                enable_native_freecad_tools=self._old_settings.enable_native_freecad_tools,
                native_tool_workbenches=self._old_settings.native_tool_workbenches,
            )
        )

    def tearDown(self):
        save_settings(self._old_settings)
