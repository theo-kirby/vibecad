# SPDX-License-Identifier: LGPL-2.1-or-later

import contextlib
import json
from pathlib import Path
import sys
import tempfile
import types

from VibeCADCore import (
    VibeCADService,
)
from VibeCADProvider import (
    ProviderUnavailable,
    OpenAIAgentsProvider,
)
from VibeCADSession import (
    make_provider_tool_runner,
    run_prompt,
)

from vibecad_tests.support import (
    SettingsSnapshotTestCase,
    _temporary_vibecad_home,
)


class _FakeDocObject:
    def __init__(self, name: str, label: str) -> None:
        self.Name = name
        self.Label = label
        self.ViewObject = types.SimpleNamespace(Visibility=True)


class _FakeView:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name.startswith("view"):
            def _orient() -> None:
                self.calls.append(name)
            return _orient
        raise AttributeError(name)

    def fitAll(self) -> None:  # noqa: N802 - FreeCAD naming
        self.calls.append("fitAll")

    def saveImage(self, path, width, height, background):  # noqa: N802
        self.calls.append(f"saveImage:{width}x{height}:{background}")
        Path(path).write_bytes(b"not-a-real-png")


@contextlib.contextmanager
def _fake_view_environment(objects: list[_FakeDocObject], with_view: bool = True):
    """Patch FreeCAD/FreeCADGui so view tools see a fake document and 3D view."""
    by_name = {obj.Name: obj for obj in objects}

    class _FakeDocument:
        Name = "FakeViewDoc"

        @staticmethod
        def getObject(name):  # noqa: N802 - FreeCAD naming
            return by_name.get(name)

        @staticmethod
        def getObjectsByLabel(label):  # noqa: N802 - FreeCAD naming
            return [obj for obj in objects if obj.Label == label]

    view = _FakeView()
    fake_app = types.ModuleType("FreeCAD")
    fake_app.ActiveDocument = _FakeDocument()
    fake_gui = types.ModuleType("FreeCADGui")
    if with_view:
        fake_gui.ActiveDocument = types.SimpleNamespace(ActiveView=view)
    else:
        fake_gui.ActiveDocument = None

    saved = {name: sys.modules.get(name) for name in ("FreeCAD", "FreeCADGui")}
    sys.modules["FreeCAD"] = fake_app
    sys.modules["FreeCADGui"] = fake_gui
    try:
        yield view
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class TestVibeCADCoreMisc(SettingsSnapshotTestCase):
    def test_open_document_requirement_uses_successful_tool_trace(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service)
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "missing-model.FCStd"
            result = runner(
                "core.open_document",
                json.dumps({"file_path": str(missing_path)}),
            )
        self.assertFalse(result["ok"])
        self.assertFalse(
            make_provider_tool_runner(service)(
                "part.set_placement",
                '{"object_name": "NoSuchObject", "x": 0}',
            )["ok"]
        )

    def test_delete_object_removes_existing_object_for_iteration(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDeleteObjectIterationTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "WrongBlock")
            box.Label = "Wrong Block"
            doc.recompute()
            object_name = box.Name
            self.assertIsNotNone(doc.getObject(object_name))

            delete_result = service.registry.call(
                "core.delete_object",
                object_name="Wrong Block",
                reason="Replace with corrected geometry",
            )
            self.assertTrue(delete_result["ok"], delete_result)
            self.assertIsNone(doc.getObject(object_name))
            self.assertEqual(delete_result["before"]["object_count"], 1)
            self.assertEqual(delete_result["after"]["object_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_core_tool_descriptions_do_not_advertise_gui_command_fallbacks(self):
        service = VibeCADService()

        def _description(tool_name):
            return str(service.registry.get(tool_name).to_schema().get("description", "")).lower()

        names = set(service.registry.names())
        self.assertNotIn("core.run_workbench_command", names)
        self.assertNotIn("fallback", _description("core.list_active_workbench_commands"))
        self.assertNotIn("core.run_workbench_command", _description("core.list_active_workbench_commands"))
        self.assertIn("not directly executable", _description("core.list_active_workbench_commands"))
        self.assertIn(
            "core.list_active_workbench_commands", _description("core.list_registered_commands")
        )
        self.assertIn("core.list_workbench_objects", _description("core.get_object_properties"))
        self.assertIn("core.delete_object", _description("core.undo_last_vibecad_action"))
        self.assertIn("core.undo_last_vibecad_action", _description("core.delete_object"))
        self.assertIn("techdraw.add_view", _description("techdraw.create_page"))
        self.assertIn("techdraw.create_page", _description("techdraw.add_view"))

        # Read-only utility tools stay tight: at most two sentences.
        for tool_name in (
            "core.get_active_document",
            "core.get_selection",
            "core.get_view_state",
            "core.get_task_panel",
            "core.get_report_view_errors",
            "core.list_workbenches",
            "core.capture_view_screenshot",
        ):
            description = str(service.registry.get(tool_name).to_schema().get("description", ""))
            sentence_count = description.count(". ") + 1
            self.assertLessEqual(sentence_count, 2, f"{tool_name}: {description}")
            self.assertLessEqual(len(description.split()), 30, f"{tool_name}: {description}")

    def test_run_prompt_rejects_empty_prompt(self):
        with self.assertRaises(ValueError):
            run_prompt(" ", service=VibeCADService(), prefer_online=False)

    def test_activate_workbench_reports_failure_without_gui(self):
        result = VibeCADService().activate_workbench("NoSuchWorkbench")
        self.assertIn("activated", result)
        self.assertIn("requested", result)

    def test_agents_provider_fails_cleanly_when_sdk_missing(self):
        try:
            import agents  # noqa: F401
        except Exception:
            with self.assertRaises(ProviderUnavailable):
                OpenAIAgentsProvider().run("hello", {})

    def test_set_view_rejects_unknown_orientation(self):
        result = VibeCADService().registry.call("core.set_view", orientation="sideways")
        self.assertFalse(result["ok"], result)
        self.assertIn("sideways", result["error"])
        self.assertIn("isometric", result["allowed_orientations"])
        self.assertIn("none", result["allowed_orientations"])

    def test_view_tool_schemas_declare_framing_and_staleness_parameters(self):
        registry = VibeCADService().registry
        screenshot_params = registry.get("core.capture_view_screenshot").parameters["properties"]
        self.assertIn("orientation", screenshot_params)
        self.assertIn("fit_all", screenshot_params)
        set_view_params = registry.get("core.set_view").parameters["properties"]
        for parameter in ("orientation", "fit_all", "show_objects", "hide_objects"):
            self.assertIn(parameter, set_view_params)
        report_params = registry.get("core.get_report_view_errors").parameters["properties"]
        self.assertIn("include_stale", report_params)

    def test_set_view_applies_orientation_and_per_object_visibility(self):
        service = VibeCADService()
        bracket = _FakeDocObject("Bracket", "Mounting Bracket")
        shaft = _FakeDocObject("Shaft", "Drive Shaft")
        with _fake_view_environment([bracket, shaft]) as view:
            result = service.set_view(
                orientation="front",
                fit_all=True,
                show_objects=["Mounting Bracket"],  # resolved by Label
                hide_objects=["Shaft", "NoSuchThing"],  # by Name + unknown
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["orientation"], "front")
        self.assertTrue(result["oriented"])
        self.assertTrue(result["fit_all"])
        self.assertEqual(result["shown"], ["Bracket"])
        self.assertEqual(result["hidden"], ["Shaft"])
        self.assertEqual(result["unknown_objects"], ["NoSuchThing"])
        self.assertTrue(bracket.ViewObject.Visibility)
        self.assertFalse(shaft.ViewObject.Visibility)
        self.assertEqual(view.calls, ["viewFront", "fitAll"])

    def test_set_view_visibility_only_succeeds_without_3d_view(self):
        service = VibeCADService()
        gear = _FakeDocObject("Gear", "Gear")
        with _fake_view_environment([gear], with_view=False):
            result = service.set_view(hide_objects=["Gear"])
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["oriented"])
        self.assertEqual(result["hidden"], ["Gear"])
        self.assertFalse(gear.ViewObject.Visibility)

    def test_capture_view_screenshot_rejects_unknown_orientation(self):
        result = VibeCADService().registry.call(
            "core.capture_view_screenshot", orientation="sideways"
        )
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["captured"])
        self.assertIn("isometric", result["allowed_orientations"])

    def test_capture_view_screenshot_defaults_and_framing_overrides(self):
        service = VibeCADService()
        with _temporary_vibecad_home():
            # Default: axometric + fitAll, exactly the pre-parameter behavior.
            with _fake_view_environment([]) as view:
                default_result = service.registry.call("core.capture_view_screenshot")
            self.assertTrue(default_result["captured"], default_result)
            self.assertEqual(default_result["orientation"], "axometric")
            self.assertTrue(default_result["fit_all"])
            self.assertEqual(
                view.calls,
                ["viewAxometric", "fitAll", "saveImage:1280x900:White"],
            )

            # orientation=none + fit_all=false preserves framing set elsewhere.
            with _fake_view_environment([]) as view:
                framed_result = service.registry.call(
                    "core.capture_view_screenshot",
                    orientation="none",
                    fit_all=False,
                )
            self.assertTrue(framed_result["captured"], framed_result)
            self.assertEqual(framed_result["orientation"], "none")
            self.assertFalse(framed_result["fit_all"])
            self.assertEqual(view.calls, ["saveImage:1280x900:White"])
