#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Audit VibeCAD open-and-modify workflow in real FreeCAD GUI."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except Exception as exc:  # pragma: no cover - requires GUI FreeCAD
    print(json.dumps({"ok": False, "error": f"PySide unavailable: {exc}"}))
    sys.exit(1)

from VibeCADCore import VibeCADService
from VibeCADPreferences import VibeCADSettings, load_settings, save_settings
from VibeCADSession import make_provider_tool_runner, _request_policy


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "build"
    / "release"
    / "Mod"
    / "CAM"
    / "CAMTests"
    / "boxtest.fcstd"
)
_OLD_SETTINGS = None


def process_events(repeats: int = 5) -> None:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for _ in range(repeats):
        app.processEvents()


def main() -> int:
    global _OLD_SETTINGS
    failures = []
    for document in list(App.listDocuments().values()):
        App.closeDocument(document.Name)

    main_window = Gui.getMainWindow()
    main_window.resize(1400, 900)
    main_window.show()
    process_events()

    if not FIXTURE.exists():
        failures.append(f"fixture missing: {FIXTURE}")
        print(json.dumps({"ok": False, "failures": failures}, indent=2, sort_keys=True))
        return 1

    _OLD_SETTINGS = load_settings()
    save_settings(
        VibeCADSettings(
            use_online_provider=_OLD_SETTINGS.use_online_provider,
            model=_OLD_SETTINGS.model,
            dotenv_path=_OLD_SETTINGS.dotenv_path,
            disabled_workbenches=_OLD_SETTINGS.disabled_workbenches,
            reasoning_effort=_OLD_SETTINGS.reasoning_effort,
            allow_primitive_provider_tools=True,
        )
    )
    Gui.activateWorkbench("PartWorkbench")
    process_events()

    opened_doc = None
    try:
        opened_doc = App.openDocument(str(FIXTURE))
        App.setActiveDocument(opened_doc.Name)
        Gui.ActiveDocument = Gui.getDocument(opened_doc.Name)
        Gui.updateGui()
        process_events(10)
    except Exception as exc:
        failures.append(f"harness failed to open fixture as active UI document: {exc}")

    service = VibeCADService()
    service.update_intent_brief(
        title="Open Modify Runtime Audit",
        summary="Modify the active fixture document in place and verify the result visually.",
        requirements={
            "purpose": "prove existing-model modification flow",
            "critical_dimensions": "set the existing box to 12 x 8 x 4 mm",
            "interfaces": "none",
            "loads": "not applicable",
            "materials_process": "not applicable",
            "tolerances": "not applicable",
            "environment": "runtime GUI audit",
            "acceptance_criteria": ["existing box dimensions are updated", "viewport screenshot is captured"],
        },
        readiness_score=100,
        ready_for_next_phase=True,
    )
    approval = service.approve_intent_brief(
        approved_by="runtime-audit",
        notes="Harness-opened document is the design authority.",
        transition_to_design=True,
    )
    if not approval.get("ok"):
        failures.append(f"intent approval failed: {approval}")

    context = service.provider_context_summary()
    request_policy = _request_policy("fix this model", context)
    runner = make_provider_tool_runner(
        service,
        "PartWorkbench",
        request_policy=request_policy,
    )

    process_events(10)
    if opened_doc is None:
        failures.append("fixture was not opened as the active document")

    document = service.document_summary()
    cube_before = next(
        (
            item
            for item in document.get("objects", [])
            if item.get("name") == "Box" or item.get("label") == "Cube"
        ),
        None,
    )
    if cube_before is None:
        failures.append("active fixture document did not expose Cube/Box object")
    target_name = (
        str(cube_before.get("name") or cube_before.get("label") or "Cube")
        if isinstance(cube_before, dict)
        else "Cube"
    )

    edit_result = runner(
        "part.set_primitive_dimensions",
        json.dumps({"object_name": target_name, "length": 12, "width": 8, "height": 4}),
    )
    process_events(10)
    if not edit_result.get("ok"):
        failures.append(f"part.set_primitive_dimensions failed: {edit_result}")

    active_doc = App.ActiveDocument
    cube = active_doc.getObject(target_name) if active_doc else None
    if cube is None:
        failures.append("Cube object missing after edit")
    else:
        try:
            dimensions = [float(cube.Length), float(cube.Width), float(cube.Height)]
            if dimensions != [12.0, 8.0, 4.0]:
                failures.append(f"Cube dimensions not edited: {dimensions}")
        except Exception as exc:
            failures.append(f"could not read Cube dimensions: {exc}")

    screenshot = service.capture_view_screenshot()
    if not screenshot.get("captured"):
        failures.append(f"screenshot not captured: {screenshot}")
    elif int(screenshot.get("file_size", 0) or 0) < 1000:
        failures.append(f"screenshot file too small: {screenshot.get('file_size')}")

    final_document = service.document_summary()
    cube_summary = next(
        (
            item
            for item in final_document.get("objects", [])
            if item.get("name") == "Box" or item.get("label") == "Cube"
        ),
        None,
    )
    result = {
        "ok": not failures,
        "failures": failures,
        "fixture": str(FIXTURE),
        "setup_open_ok": opened_doc is not None,
        "preserve_existing_request": request_policy,
        "edit_ok": bool(edit_result.get("ok")),
        "document": {
            "name": final_document.get("document"),
            "object_count": final_document.get("object_count"),
            "cube": cube_summary,
        },
        "screenshot": {
            "captured": bool(screenshot.get("captured")),
            "file_size": screenshot.get("file_size"),
            "path": screenshot.get("path"),
            "visual_observation": screenshot.get("visual_observation"),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if _OLD_SETTINGS is not None:
        save_settings(_OLD_SETTINGS)
        _OLD_SETTINGS = None
    return 1 if failures else 0


def run_and_exit() -> None:
    global _OLD_SETTINGS
    code = 1
    try:
        code = main()
    except Exception:
        print(
            json.dumps(
                {"ok": False, "traceback": traceback.format_exc()},
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        if _OLD_SETTINGS is not None:
            save_settings(_OLD_SETTINGS)
            _OLD_SETTINGS = None
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.exit(code)


QtCore.QTimer.singleShot(1500, run_and_exit)
