#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Audit the VibeCAD assistant panel in every runtime FreeCAD workbench.

Run with:
    xvfb-run -a tools/freecad_venv.sh tools/vibecad_assistant_panel_runtime_audit.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except Exception as exc:  # pragma: no cover - this script requires GUI FreeCAD
    print(json.dumps({"ok": False, "error": f"PySide unavailable: {exc}"}))
    sys.exit(1)


DOMAIN_CONTEXT_BY_WORKBENCH = {
    "AssemblyWorkbench": "VibeCADAssemblyContext",
    "BIMWorkbench": "VibeCADBimContext",
    "CAMWorkbench": "VibeCADCamContext",
    "DraftWorkbench": "VibeCADDraftContext",
    "FemWorkbench": "VibeCADFemContext",
    "InspectionWorkbench": "VibeCADInspectionContext",
    "MaterialWorkbench": "VibeCADMaterialContext",
    "MeshWorkbench": "VibeCADMeshContext",
    "MeshPartWorkbench": "VibeCADMeshPartContext",
    "OpenSCADWorkbench": "VibeCADOpenSCADContext",
    "PartDesignWorkbench": "VibeCADPartDesignContext",
    "PartWorkbench": "VibeCADPartContext",
    "PointsWorkbench": "VibeCADPointsContext",
    "ReverseEngineeringWorkbench": "VibeCADReverseEngineeringContext",
    "RobotWorkbench": "VibeCADRobotContext",
    "SketcherWorkbench": "VibeCADSketcherContext",
    "SpreadsheetWorkbench": "VibeCADSpreadsheetContext",
    "SurfaceWorkbench": "VibeCADSurfaceContext",
    "TechDrawWorkbench": "VibeCADTechDrawContext",
}

DOMAIN_CONTEXT_OBJECTS = sorted(set(DOMAIN_CONTEXT_BY_WORKBENCH.values()))

REQUIRED_WIDGETS = {
    "VibeCADStatus": QtWidgets.QLabel,
    "VibeCADToolPack": QtWidgets.QLabel,
    "VibeCADOutput": QtWidgets.QPlainTextEdit,
    "VibeCADPhaseBanner": QtWidgets.QLabel,
    "VibeCADPhaseContext": QtWidgets.QPlainTextEdit,
    "VibeCADWorkflowAudit": QtWidgets.QPlainTextEdit,
    "VibeCADScreenshotStatus": QtWidgets.QLabel,
    "VibeCADPrompt": QtWidgets.QPlainTextEdit,
    "VibeCADRunStatus": QtWidgets.QLabel,
    "VibeCADCaptureView": QtWidgets.QPushButton,
    "VibeCADRunPrompt": QtWidgets.QPushButton,
    "VibeCADStopPrompt": QtWidgets.QPushButton,
    "VibeCADUseOnlineProvider": QtWidgets.QCheckBox,
}

REMOVED_WIDGETS = {
    "VibeCADAssistantTabs": QtWidgets.QTabWidget,
    "VibeCADPendingActions": QtWidgets.QPlainTextEdit,
    "VibeCADActionHistory": QtWidgets.QPlainTextEdit,
    "VibeCADActionSelector": QtWidgets.QComboBox,
    "VibeCADQuickPrompt": QtWidgets.QComboBox,
    "VibeCADInsertQuickPrompt": QtWidgets.QPushButton,
    "VibeCADRefreshActions": QtWidgets.QPushButton,
    "VibeCADApproveSelected": QtWidgets.QPushButton,
    "VibeCADRejectSelected": QtWidgets.QPushButton,
    "VibeCADReviseSelected": QtWidgets.QPushButton,
    "VibeCADUndoLastAction": QtWidgets.QPushButton,
    "VibeCADClearSession": QtWidgets.QPushButton,
}


def process_events(repeats: int = 3) -> None:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for _ in range(repeats):
        app.processEvents()


def active_workbench_name() -> str:
    workbench = Gui.activeWorkbench()
    return str(workbench.name()) if workbench else ""


def find_required(dock: QtWidgets.QDockWidget, object_name: str, widget_type):
    widget = dock.findChild(widget_type, object_name)
    if widget is None:
        raise AssertionError(f"missing widget {object_name}")
    return widget


def widget_text(widget) -> str:
    if hasattr(widget, "toPlainText"):
        return widget.toPlainText()
    if hasattr(widget, "text"):
        return widget.text()
    return ""


def visible_domain_contexts(dock: QtWidgets.QDockWidget) -> list[str]:
    visible = []
    for object_name in DOMAIN_CONTEXT_OBJECTS:
        widget = dock.findChild(QtWidgets.QPlainTextEdit, object_name)
        if widget is not None and bool(widget.property("VibeCADContextActive")):
            visible.append(object_name)
    return visible


def close_panel() -> None:
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is not None:
        dock.close()
    process_events()


def audit_workbench(workbench: str) -> dict:
    result = {
        "workbench": workbench,
        "activated": False,
        "active_workbench": "",
        "visible_domain_contexts": [],
        "missing_widgets": [],
        "failures": [],
        "workflow_audit": "",
    }

    activated = bool(Gui.activateWorkbench(workbench))
    process_events(5)
    result["activated"] = activated
    result["active_workbench"] = active_workbench_name()
    if not activated and result["active_workbench"] != workbench:
        result["failures"].append("activateWorkbench returned false")
        return result
    if result["active_workbench"] != workbench:
        result["failures"].append(
            f"active workbench mismatch: {result['active_workbench']}"
        )

    Gui.runCommand("VibeCAD_OpenAssistant")
    process_events(5)
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
    if dock is None:
        result["failures"].append("assistant dock did not open")
        return result
    if not dock.isVisible():
        result["failures"].append("assistant dock is not visible")

    for object_name, widget_type in REQUIRED_WIDGETS.items():
        try:
            widget = find_required(dock, object_name, widget_type)
            text = widget_text(widget)
            if object_name == "VibeCADStopPrompt" and widget.isEnabled():
                result["failures"].append("stop button should be disabled while idle")
            if object_name == "VibeCADOutput" and not text.strip():
                result["failures"].append("conversation output is empty")
        except AssertionError:
            result["missing_widgets"].append(object_name)

    for object_name, widget_type in REMOVED_WIDGETS.items():
        if dock.findChild(widget_type, object_name) is not None:
            result["failures"].append(f"removed widget is still present: {object_name}")

    status = dock.findChild(QtWidgets.QLabel, "VibeCADStatus")
    tool_pack = dock.findChild(QtWidgets.QLabel, "VibeCADToolPack")
    if status is None or "OpenAI:" not in status.text():
        result["failures"].append("status label does not report active workbench")
    elif workbench.removesuffix("Workbench") not in status.text():
        result["failures"].append("status label does not report active workbench")
    if tool_pack is None or f"Tool pack: {workbench}" not in tool_pack.text():
        result["failures"].append("tool-pack label does not report active pack")
    workflow_audit = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADWorkflowAudit")
    workflow_text = workflow_audit.toPlainText() if workflow_audit is not None else ""
    result["workflow_audit"] = workflow_text
    if "Workflow audit: passed" not in workflow_text:
        result["failures"].append("workflow audit does not report passed phase boundaries")
    if "Failed gates: none" not in workflow_text:
        result["failures"].append("workflow audit reports failed gates")
    phase_context = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPhaseContext")
    phase_context_text = phase_context.toPlainText() if phase_context is not None else ""
    result["phase_context"] = phase_context_text
    for forbidden in ("Brief:", "Project root:", "/tmp/"):
        if forbidden in phase_context_text:
            result["failures"].append(f"visible phase context leaks storage detail: {forbidden}")

    expected_context = DOMAIN_CONTEXT_BY_WORKBENCH.get(workbench)
    contexts = visible_domain_contexts(dock)
    result["visible_domain_contexts"] = contexts
    if expected_context:
        if contexts != [expected_context]:
            result["failures"].append(
                f"visible context mismatch: expected {expected_context}, got {contexts}"
            )
    elif contexts:
        result["failures"].append(f"unexpected visible domain contexts: {contexts}")

    if result["missing_widgets"]:
        result["failures"].append(
            "missing required widgets: " + ", ".join(result["missing_widgets"])
        )
    close_panel()
    return result


def main() -> int:
    try:
        setattr(App, "TestEnvironment", True)
        main_window = Gui.getMainWindow()
        main_window.resize(1600, 1000)
        main_window.show()
        process_events(5)

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--workbench",
            action="append",
            help="Audit only this workbench. May be passed more than once.",
        )
        argv = sys.argv[1:]
        if "--pass" in argv:
            argv = argv[argv.index("--pass") + 1 :]
        else:
            argv = []
        args = parser.parse_args(argv)

        available_workbenches = sorted(Gui.listWorkbenches().keys())
        requested_workbenches = args.workbench or available_workbenches
        workbenches = [
            workbench
            for workbench in requested_workbenches
            if workbench in available_workbenches
        ]
        missing_requested = sorted(set(requested_workbenches).difference(workbenches))
        results = []
        for workbench in workbenches:
            print(f"AUDIT_WORKBENCH {workbench}", flush=True)
            try:
                results.append(audit_workbench(workbench))
            except Exception:
                results.append(
                    {
                        "workbench": workbench,
                        "activated": False,
                        "active_workbench": active_workbench_name(),
                        "visible_domain_contexts": [],
                        "missing_widgets": [],
                        "failures": [traceback.format_exc()],
                    }
                )
                close_panel()

        try:
            Gui.activateWorkbench("PartWorkbench")
            close_panel()
        except Exception:
            pass

        failures = [item for item in results if item["failures"]]
        if missing_requested:
            failures.append(
                {
                    "workbench": "requested-workbenches",
                    "activated": False,
                    "active_workbench": active_workbench_name(),
                    "visible_domain_contexts": [],
                    "missing_widgets": [],
                    "failures": [
                        "requested workbenches are unavailable: "
                        + ", ".join(missing_requested)
                    ],
                }
            )
        print(
            json.dumps(
                {
                    "ok": not failures,
                    "workbench_count": len(workbenches),
                    "workbenches": workbenches,
                    "failure_count": len(failures),
                    "failures": failures,
                    "results": results,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if failures else 0
    finally:
        try:
            delattr(App, "TestEnvironment")
        except Exception:
            pass


def run_and_exit() -> None:
    code = 1
    try:
        code = main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.exit(code)


QtCore.QTimer.singleShot(1500, run_and_exit)
