"""Smoke test: verify Gui.getMainWindow().addDockWindow() routes through
DockWindowManager and produces a dock with the native OverlayTitle title bar.

Run headless:
    QT_QPA_PLATFORM=offscreen ./build/release/bin/FreeCAD tools/vibecad_panel_dock_audit.py

The result is printed to stdout as a single line starting with
DOCK_AUDIT_RESULT and also written to /tmp/vibecad_dock_audit.json.
FreeCAD is closed automatically once the audit finishes.
"""

import json
import sys

RESULT_PATH = "/tmp/vibecad_dock_audit.json"

result = {"ok": False, "titleBar": None, "error": None}

try:
    import FreeCADGui as Gui
    from PySide6 import QtWidgets

    mw = Gui.getMainWindow()

    widget = QtWidgets.QLabel("dock smoke test")
    widget.setObjectName("DockSmokeTestWidget")
    widget.setWindowTitle("Dock Smoke Test")

    dock = mw.addDockWindow(widget, "DockSmokeTest", "right")

    title_bar = dock.titleBarWidget()
    result["titleBar"] = title_bar.objectName() if title_bar is not None else None
    result["dockObjectName"] = dock.objectName()
    result["dockClass"] = dock.metaObject().className()
    result["ok"] = result["titleBar"] == "OverlayTitle"

    # cleanup
    mw.removeDockWindow("DockSmokeTest")
except Exception as exc:  # noqa: BLE001 - report anything for the audit
    result["error"] = f"{type(exc).__name__}: {exc}"

line = "DOCK_AUDIT_RESULT " + json.dumps(result)
print(line)
sys.stdout.flush()
with open(RESULT_PATH, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(result))

# Quit FreeCAD so headless runs terminate on their own.
try:
    from PySide6 import QtCore

    QtCore.QTimer.singleShot(0, QtCore.QCoreApplication.instance().quit)
except Exception:  # noqa: BLE001 - best effort shutdown
    pass
