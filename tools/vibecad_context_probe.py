#!/usr/bin/env python3

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "release" / "Mod" / "VibeCAD"))

import FreeCAD as App  # noqa: E402
from PySide import QtCore, QtWidgets  # noqa: E402

from VibeCADCore import VibeCADService  # noqa: E402


def main() -> int:
    doc = App.newDocument(f"VibeCADContextProbe{int(time.time() * 1000)}")
    try:
        service = VibeCADService()
        service.registry.call("core.create_new_document", name=doc.Name)
        service.registry.call("part.create_primitive", primitive_type="box", label="Probe Box")
        service._last_view_screenshot = {"captured": True, "path": "/tmp/vibecad-test.png"}
        service.record_conversation_turn("user", "remember this")
        service.clear_local_session()
        checks = [
            ("auth", service.auth_state),
            ("document", service.document_summary),
            ("selection", service.selection_summary),
            ("view", service.view_state),
            ("task_panel", service.task_panel_summary),
            ("view_screenshot", service.view_screenshot_summary),
            ("workbenches", service.workbench_summary),
            ("workbench_tool_pack", service.workbench_tool_pack_summary),
            ("workbench_commands", service.workbench_command_summary),
            ("workbench_object_templates", service.workbench_object_templates),
            ("workbench_objects", service.workbench_object_summary),
            ("part", service.part_summary),
            ("mesh", service.mesh_summary),
            ("points", service.points_summary),
            ("material", service.material_summary),
            ("sketcher", service.sketcher_summary),
            ("spreadsheet", service.spreadsheet_summary),
            ("draft", service.draft_summary),
            ("partdesign", service.partdesign_summary),
            ("techdraw", service.techdraw_summary),
            ("fem", service.fem_summary),
            ("cam", service.cam_summary),
            ("bim", service.bim_summary),
            ("assembly", service.assembly_summary),
            ("inspection", service.inspection_summary),
            ("openscad", service.openscad_summary),
            ("surface", service.surface_summary),
            ("reverseengineering", service.reverseengineering_summary),
            ("robot", service.robot_summary),
            ("meshpart", service.meshpart_summary),
            ("provider_tool_surface", service.provider_tool_surface),
            ("tool_shape_report", service.tool_shape_report),
            ("conversation", service.conversation_history),
            ("report_view_errors", service.report_view_errors),
        ]
        for name, func in checks:
            print(f"START {name}", flush=True)
            func()
            print(f"END {name}", flush=True)
        print("START context_summary", flush=True)
        service.context_summary()
        print("END context_summary", flush=True)
    finally:
        App.closeDocument(doc.Name)
    return 0


def run_and_exit() -> None:
    code = main()
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.exit(code)


QtCore.QTimer.singleShot(0, run_and_exit)
