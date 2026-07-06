# SPDX-License-Identifier: LGPL-2.1-or-later

import importlib
from pathlib import Path
import sys
import tempfile
import types

from VibeCADCore import (
    VibeCADService,
    get_service,
)
from VibeCADPreferences import (
    VibeCADSettings,
    load_settings,
    save_settings,
)
from VibeCADSession import (
    _screenshot_requirement_satisfied,
)

from vibecad_tests.support import (
    SettingsSnapshotTestCase,
)


class TestVibeCADAssistantPanel(SettingsSnapshotTestCase):
    def test_cpp_and_python_workbenches_expose_vibecad_gui_actions(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        expected_actions = {
            "Ask AI",
            "Explain Selection",
            "Open AI Assistant",
            "AI Preferences",
            "AI Auth Status",
        }

        def menu_action_texts(menu):
            texts = []
            for action in menu.actions():
                text = action.text().replace("&", "").strip()
                if text:
                    texts.append(text)
                child_menu = action.menu()
                if child_menu:
                    texts.extend(menu_action_texts(child_menu))
            return texts

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        runtime_workbenches = [
            "DraftWorkbench",
            "PartWorkbench",
            "SketcherWorkbench",
            "TestWorkbench",
        ]
        missing = {}
        try:
            for workbench in runtime_workbenches:
                activated = Gui.activateWorkbench(workbench)
                self.assertTrue(activated, workbench)
                if app:
                    app.processEvents()
                main_window = Gui.getMainWindow()
                menu_hits = expected_actions.intersection(menu_action_texts(main_window.menuBar()))
                toolbar_texts = []
                for toolbar in main_window.findChildren(QtWidgets.QToolBar):
                    for action in toolbar.actions():
                        text = action.text().replace("&", "").strip()
                        if text:
                            toolbar_texts.append(text)
                toolbar_hits = expected_actions.intersection(toolbar_texts)
                if menu_hits != expected_actions or toolbar_hits != expected_actions:
                    missing[workbench] = {
                        "menu": sorted(expected_actions.difference(menu_hits)),
                        "toolbar": sorted(expected_actions.difference(toolbar_hits)),
                    }
        finally:
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()
        self.assertEqual({}, missing)

    def test_workbench_registration_adds_vibecad_context_menu_group(self):
        try:
            import FreeCADGui as Gui  # noqa: F401
            import VibeCADGui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/VibeCADGui unavailable")

        if QtWidgets.QApplication.instance() is None:
            self.skipTest("QApplication unavailable")

        class FakeNativeWorkbench:
            def __init__(self):
                self.toolbars = []
                self.menus = []
                self.context_menus = []

            def appendToolbar(self, name, commands):
                self.toolbars.append((name, list(commands)))

            def appendMenu(self, name, commands):
                self.menus.append((list(name), list(commands)))

            def appendContextMenu(self, name, commands):
                self.context_menus.append((name, list(commands)))

        class FakeWorkbench:
            pass

        native = FakeNativeWorkbench()
        workbench = FakeWorkbench()
        workbench.__Workbench__ = native

        VibeCADGui.register_ai_commands_for_workbench(workbench, "Fake")

        self.assertIn(("AI", VibeCADGui.COMMANDS), native.toolbars)
        self.assertIn((["AI"], VibeCADGui.COMMANDS), native.menus)
        self.assertIn(("VibeCAD", VibeCADGui.CONTEXT_COMMANDS), native.context_menus)
        self.assertIn("VibeCAD_ExplainSelection", VibeCADGui.CONTEXT_COMMANDS)
        self.assertIn("VibeCAD_OpenAssistant", VibeCADGui.CONTEXT_COMMANDS)

    def test_assistant_panel_shows_only_active_workbench_context(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()

        def open_panel(workbench):
            Gui.activateWorkbench(workbench)
            Gui.runCommand("VibeCAD_OpenAssistant")
            if app:
                app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            return dock

        try:
            part_dock = open_panel("PartWorkbench")
            self.assertTrue(
                part_dock.findChild(
                    QtWidgets.QPlainTextEdit,
                    "VibeCADPartContext",
                ).property("VibeCADContextActive")
            )
            self.assertIn(
                "No provider tool calls yet.",
                part_dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADToolTrace").toPlainText(),
            )
            self.assertIsNotNone(
                part_dock.findChild(QtWidgets.QLabel, "VibeCADScreenshotStatus")
            )
            self.assertIsNone(
                part_dock.findChild(QtWidgets.QTabWidget, "VibeCADAssistantTabs")
            )
            self.assertIsNone(
                part_dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPendingActions")
            )
            self.assertIsNone(
                part_dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADActionHistory")
            )
            self.assertIsNone(
                part_dock.findChild(QtWidgets.QPushButton, "VibeCADApproveSelected")
            )
            stop_button = part_dock.findChild(QtWidgets.QPushButton, "VibeCADStopPrompt")
            self.assertIsNotNone(stop_button)
            self.assertFalse(stop_button.isEnabled())
            self.assertFalse(
                part_dock.findChild(
                    QtWidgets.QPlainTextEdit,
                    "VibeCADDraftContext",
                ).property("VibeCADContextActive")
            )

            draft_dock = open_panel("DraftWorkbench")
            self.assertTrue(
                draft_dock.findChild(
                    QtWidgets.QPlainTextEdit,
                    "VibeCADDraftContext",
                ).property("VibeCADContextActive")
            )
            self.assertFalse(
                draft_dock.findChild(
                    QtWidgets.QPlainTextEdit,
                    "VibeCADPartContext",
                ).property("VibeCADContextActive")
            )
        finally:
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()

    def test_assistant_panel_opens_when_integrated_workbench_is_activated(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
            import VibeCADGui
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()
        VibeCADGui.ensure_commands_registered()
        dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
        if dock is not None:
            dock.close()
        try:
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()
            Gui.activateWorkbench("DraftWorkbench")
            if app:
                for _ in range(3):
                    app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            self.assertTrue(dock.isVisible())
            status = dock.findChild(QtWidgets.QLabel, "VibeCADStatus")
            tool_pack = dock.findChild(QtWidgets.QLabel, "VibeCADToolPack")
            self.assertIn("Workbench: Draft", status.text())
            self.assertIn("Tool pack: DraftWorkbench", tool_pack.text())
        finally:
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()

    def test_assistant_panel_defaults_to_task_side_dock(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtCore
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()
        try:
            Gui.activateWorkbench("PartWorkbench")
            Gui.runCommand("VibeCAD_OpenAssistant")
            if app:
                app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            self.assertTrue(dock.isVisible())
            self.assertFalse(dock.isFloating())
            self.assertTrue(dock.features() & QtWidgets.QDockWidget.DockWidgetFloatable)
            self.assertTrue(
                dock.allowedAreas()
                & (QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
            )
            self.assertEqual(
                main_window.dockWidgetArea(dock),
                QtCore.Qt.RightDockWidgetArea,
            )
            self.assertLessEqual(dock.width(), 560)
        finally:
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()

    def test_assistant_panel_reports_disabled_tool_pack(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        old_settings = load_settings()
        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()
        try:
            save_settings(VibeCADSettings(disabled_workbenches=("PartWorkbench",)))
            Gui.activateWorkbench("PartWorkbench")
            Gui.runCommand("VibeCAD_OpenAssistant")
            if app:
                app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            tool_pack = dock.findChild(QtWidgets.QLabel, "VibeCADToolPack")
            provider_tools = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADProviderTools")
            self.assertIn("PartWorkbench", tool_pack.text())
            self.assertIn("disabled", tool_pack.text())
            self.assertNotIn("part.get_objects", provider_tools.toPlainText())
            self.assertIn("core.get_active_document", provider_tools.toPlainText())
        finally:
            save_settings(old_settings)
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()

    def test_assistant_panel_capture_view_updates_context(self):
        try:
            import FreeCAD as App
            import FreeCADGui as Gui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()
        doc = App.newDocument("VibeCADCaptureViewTest")
        screenshot_path = None
        try:
            doc.addObject("Part::Box", "CaptureBox")
            doc.recompute()
            Gui.activateWorkbench("PartWorkbench")
            Gui.runCommand("VibeCAD_OpenAssistant")
            if app:
                app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            button = dock.findChild(QtWidgets.QPushButton, "VibeCADCaptureView")
            status = dock.findChild(QtWidgets.QLabel, "VibeCADScreenshotStatus")
            self.assertIsNotNone(button)
            button.click()
            if app:
                app.processEvents()
            self.assertIn("View attached:", status.text())
            summary = get_service().view_screenshot_summary()
            self.assertTrue(summary["captured"])
            self.assertEqual(summary["format"], "png")
            observation = summary.get("visual_observation", {})
            self.assertTrue(observation.get("available"), observation)
            self.assertFalse(observation.get("mostly_blank"), observation)
            screenshot_path = Path(summary["path"])
            self.assertTrue(screenshot_path.exists())
            self.assertNotIn("OPENAI_API_KEY", str(summary))
        finally:
            if screenshot_path is not None:
                try:
                    screenshot_path.unlink()
                except Exception:
                    pass
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            App.closeDocument(doc.Name)
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()

    def test_core_capture_view_screenshot_tool_returns_canonical_schema(self):
        module = importlib.import_module("tool_impl.service.core_capture_view_screenshot")

        class FakeView:
            def viewAxometric(self):
                pass

            def fitAll(self):
                pass

            def saveImage(self, path, width, height, background):
                Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2048)

        class FakeGuiDocument:
            ActiveView = FakeView()

        class FakeWorkbench:
            def name(self):
                return "PartDesignWorkbench"

        fake_app = types.SimpleNamespace(ActiveDocument=types.SimpleNamespace(Name="VibeCADTestDoc"))
        fake_gui = types.SimpleNamespace(
            ActiveDocument=FakeGuiDocument(),
            activeWorkbench=lambda: FakeWorkbench(),
        )

        original_app = sys.modules.get("FreeCAD")
        original_gui = sys.modules.get("FreeCADGui")
        sys.modules["FreeCAD"] = fake_app
        sys.modules["FreeCADGui"] = fake_gui
        screenshot_root = None
        service = None
        try:
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
                screenshot_root = Path(directory) / "vibecad-project"

                class FakeService:
                    _last_view_screenshot = None

                    def project_context(self):
                        return {"root": str(screenshot_root)}

                    def _screenshot_visual_observation(self, path):
                        return {"available": True, "mostly_blank": False}

                service = FakeService()
                result = module.run(service)
            self.assertTrue(result["ok"])
            self.assertTrue(result["captured"])
            self.assertGreater(result["file_size"], 1000)
            self.assertEqual(result["format"], "png")
            self.assertEqual(result["background"], "White")
            self.assertEqual(result["artifact_role"], "visual_verification")
            self.assertEqual(result["workbench"], "PartDesignWorkbench")
            self.assertEqual(result["document"], "VibeCADTestDoc")
            self.assertTrue(str(result["path"]).startswith(str(screenshot_root)))
            self.assertIn("/screenshots/", str(result["path"]))
            self.assertNotIn("exists", result)
            self.assertNotIn("size_bytes", result)
            self.assertEqual(service._last_view_screenshot, result)
        finally:
            path = (
                service._last_view_screenshot.get("path")
                if service is not None and service._last_view_screenshot
                else None
            )
            if path:
                try:
                    Path(path).unlink()
                except Exception:
                    pass
            if original_app is None:
                sys.modules.pop("FreeCAD", None)
            else:
                sys.modules["FreeCAD"] = original_app
            if original_gui is None:
                sys.modules.pop("FreeCADGui", None)
            else:
                sys.modules["FreeCADGui"] = original_gui

    def test_screenshot_visual_observation_detects_visible_content(self):
        try:
            from PySide import QtCore, QtGui
        except Exception:
            self.skipTest("Qt bindings unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible-model.png"
            image = QtGui.QImage(120, 80, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            painter = QtGui.QPainter(image)
            painter.fillRect(QtCore.QRect(35, 20, 50, 35), QtGui.QColor("black"))
            painter.end()
            self.assertTrue(image.save(str(path)))

            observation = VibeCADService._screenshot_visual_observation(path)
            self.assertTrue(observation["available"], observation)
            self.assertFalse(observation["mostly_blank"], observation)
            self.assertGreater(observation["foreground_pixel_ratio"], 0.01)
            self.assertIsNotNone(observation["foreground_bbox"])
            self.assertEqual(observation["foreground_component_count"], 1)
            self.assertGreater(observation["foreground_bbox_coverage"], 0.1)
            self.assertEqual(observation["attention_flags"], [])
            self.assertIn("bbox covers", observation["layout_summary"])

    def test_screenshot_visual_observation_reports_fragmented_layout(self):
        try:
            from PySide import QtCore, QtGui
        except Exception:
            self.skipTest("Qt bindings unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fragmented-model.png"
            image = QtGui.QImage(160, 100, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            painter = QtGui.QPainter(image)
            for rect in (
                QtCore.QRect(8, 8, 16, 14),
                QtCore.QRect(132, 8, 16, 14),
                QtCore.QRect(8, 76, 16, 14),
                QtCore.QRect(132, 76, 16, 14),
                QtCore.QRect(72, 43, 16, 14),
            ):
                painter.fillRect(rect, QtGui.QColor("black"))
            painter.end()
            self.assertTrue(image.save(str(path)))

            observation = VibeCADService._screenshot_visual_observation(path)
            self.assertTrue(observation["available"], observation)
            self.assertFalse(observation["mostly_blank"], observation)
            self.assertGreaterEqual(observation["foreground_component_count"], 5)
            self.assertIn("fragmented_view", observation["attention_flags"])
            self.assertLess(observation["largest_component_pixel_ratio"], 0.75)

    def test_screenshot_gate_requires_provider_readable_nonblank_observation(self):
        service = VibeCADService()
        service._last_view_screenshot = {
            "captured": True,
            "path": "/tmp/vibecad-metadata-only.png",
            "file_size": 2048,
            "format": "png",
        }
        self.assertFalse(_screenshot_requirement_satisfied(service))

        service._last_view_screenshot["visual_observation"] = {
            "available": True,
            "foreground_pixel_ratio": 0.0,
            "mostly_blank": True,
            "inspection_summary": "No visible non-background model content detected.",
        }
        self.assertFalse(_screenshot_requirement_satisfied(service))

        service._last_view_screenshot["visual_observation"] = {
            "available": True,
            "foreground_pixel_ratio": 0.08,
            "foreground_bbox": [5, 5, 90, 60],
            "attention_flags": ["fragmented_view"],
            "mostly_blank": False,
            "inspection_summary": "Visible non-background model content detected in the viewport screenshot.",
        }
        self.assertTrue(_screenshot_requirement_satisfied(service))

        service._last_view_screenshot["visual_observation"] = {
            "available": True,
            "foreground_pixel_ratio": 0.08,
            "foreground_bbox": [5, 5, 90, 60],
            "attention_flags": [],
            "mostly_blank": False,
            "inspection_summary": "Visible non-background model content detected in the viewport screenshot.",
        }
        self.assertTrue(_screenshot_requirement_satisfied(service))

    def test_assistant_panel_does_not_show_quick_prompt_controls(self):
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
        except Exception:
            self.skipTest("FreeCADGui/PySide unavailable")

        app = QtWidgets.QApplication.instance()
        if app is None:
            self.skipTest("QApplication unavailable")
        main_window = Gui.getMainWindow()
        try:
            Gui.activateWorkbench("PartWorkbench")
            Gui.runCommand("VibeCAD_OpenAssistant")
            if app:
                app.processEvents()
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            self.assertIsNotNone(dock)
            prompt = dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADPrompt")
            self.assertIsNotNone(prompt)
            self.assertIsNone(dock.findChild(QtWidgets.QComboBox, "VibeCADQuickPrompt"))
            self.assertIsNone(dock.findChild(QtWidgets.QPushButton, "VibeCADInsertQuickPrompt"))
            self.assertNotIn("Quick prompt", dock.findChild(QtWidgets.QPlainTextEdit, "VibeCADOutput").toPlainText())
        finally:
            dock = main_window.findChild(QtWidgets.QDockWidget, "VibeCADAssistantPanel")
            if dock is not None:
                dock.close()
            Gui.activateWorkbench("PartWorkbench")
            if app:
                app.processEvents()
