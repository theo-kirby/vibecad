#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Ask the live VibeCAD provider to critique provider-visible tool shapes."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import FreeCAD as App
from PySide import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "release" / "Mod" / "VibeCAD"))

from VibeCADCore import VibeCADService
from VibeCADSession import run_prompt


PROMPT = """
You are evaluating VibeCAD's provider-visible CAD tool shape, not creating a CAD model.

Use the available VibeCAD tools to inspect:
- active workbench tool surface
- PartDesign and Sketcher tool schemas
- tool shape report
- current document/sketch context shape if useful

Then report, as the AI model that must drive these tools, what makes the current
tool shape confusing or inefficient for creating a complex robot arm using native
FreeCAD-style steps. Be specific. Focus on:
- tool result fields missing after create_sketch, sketcher geometry calls, pad/pocket failures, checkpoints, and workbench switches
- what exact next_action / active_object / readiness fields should be returned
- which tool schemas should be split, renamed, or extended
- what context should be shown at the start of each turn so you do not waste turns
- what would have prevented the prior loop from switching workbenches twice, creating circles, then stalling after a checkpoint

Do not make geometry. Return a concise engineering critique with concrete schema/result changes.
"""


def main() -> int:
    progress: list[dict] = []
    service = VibeCADService()
    response = run_prompt(
        PROMPT,
        service=service,
        prefer_online=True,
        progress_callback=progress.append,
        enforce_small_steps=False,
    )
    print(
        json.dumps(
            {
                "ok": response.error is None,
                "provider": response.provider,
                "error": response.error,
                "final_output": response.final_output,
                "tool_trace": response.tool_trace,
                "progress": progress,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0 if response.error is None else 1


def run_and_exit() -> None:
    code = 1
    try:
        code = main()
    except Exception:
        print(json.dumps({"ok": False, "traceback": traceback.format_exc()}, indent=2))
    finally:
        for doc in list(App.listDocuments().values()):
            try:
                App.closeDocument(doc.Name)
            except Exception:
                pass
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.exit(code)


QtCore.QTimer.singleShot(1000, run_and_exit)
