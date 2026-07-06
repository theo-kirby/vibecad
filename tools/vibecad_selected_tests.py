#!/usr/bin/env python3

"""Run selected VibeCAD unittest names inside FreeCAD."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "release" / "Mod" / "VibeCAD"))

import FreeCAD as App  # noqa: E402  (requires sys.path setup above)
from PySide import QtCore, QtWidgets  # noqa: E402


def main() -> int:
    names = [item for item in sys.argv[1:] if item.startswith("TestVibeCAD.")]
    if not names:
        print("usage: vibecad_selected_tests.py TEST_NAME [TEST_NAME ...]", file=sys.stderr)
        return 2
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for name in names:
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_and_exit() -> None:
    code = main()
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.exit(code)


if App.GuiUp:
    # GUI event loop is (about to be) running: defer until it starts.
    QtCore.QTimer.singleShot(0, run_and_exit)
else:
    # FreeCADCmd never spins a Qt event loop; a queued singleShot would
    # never fire and its pending Python-holding event would be destroyed
    # during Qt static teardown, after Python finalization -> SIGSEGV.
    # Run synchronously and drain any events posted by the tests.
    exit_code = main()
    core_app = QtCore.QCoreApplication.instance()
    if core_app is not None:
        core_app.processEvents()
    sys.exit(exit_code)
