# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import importlib
import inspect
import json
import re
import runpy
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from urllib import error

from VibeCADAuth import (
    AuthStatus,
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    delete_keyring_key,
    read_dotenv_key,
    read_keyring_key,
    redact_secret,
    resolve_auth_state,
    store_keyring_key,
    validate_configured_openai_auth,
    validate_openai_api_key,
)
import VibeCADPreferences
from VibeCADCore import VibeCADService, get_service
from VibeCADPreferences import (
    DEFAULT_REASONING_EFFORT,
    DEFAULT_MODEL,
    PreferencesPage,
    REASONING_EFFORTS,
    VibeCADSettings,
    load_settings,
    normalize_reasoning_effort,
    preferences,
    reset_settings,
    save_settings,
)
from VibeCADProvider import (
    BaseProvider,
    OfflineProvider,
    ProviderResult,
    ProviderUnavailable,
    OpenAIAgentsProvider,
    _agents_input_from_context,
    _build_provider_function_tools,
    _model_visible_context,
    _provider_tool_request_schema,
    _run_agents_subprocess,
    _write_openai_request_dump,
)
from VibeCADSession import (
    MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN,
    MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN_ENV,
    ProviderToolScope,
    VibeCADResponse,
    _assistant_stopped_without_finishing,
    _effective_provider_workbench,
    _execution_contract_for_context,
    _max_mutating_tool_calls_per_provider_turn,
    _missing_requirement_lines,
    _prompt_with_conversation,
    _provider_loop_state,
    _result_summary,
    _should_continue_autonomously,
    _screenshot_requirement_satisfied,
    _tool_batch_checkpoint_reached,
    make_provider_tool_runner,
    provider_tool_scope_for_context,
    provider_safe_tool_schemas,
    run_prompt,
)
from VibeCADTools import SafetyLevel, ToolRegistry, VibeCADTool
from VibeCADTransactions import (
    ApprovalQueue,
    _bounded_report_view_line,
    _is_report_view_error_line,
    run_freecad_transaction,
)
from VibeCADWorkbenchTools import WORKBENCH_TOOL_PACKS, get_tool_pack


def _repo_tool_script(name: str) -> Path:
    candidates = [
        Path.cwd() / "tools" / name,
        Path.cwd().parent.parent / "tools" / name,
        Path(__file__).resolve().parents[3] / "tools" / name,
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


class TestVibeCADAuth(unittest.TestCase):
    def test_redacts_api_key(self):
        self.assertEqual(redact_secret("sk-test123456"), "sk-...3456")

    def test_resolves_environment_key_without_exposing_secret(self):
        state = resolve_auth_state(env={"OPENAI_API_KEY": "sk-test123456"})
        self.assertEqual(state.status, AuthStatus.CONFIGURED_UNVERIFIED)
        self.assertEqual(state.source, "environment")
        self.assertNotIn("test123456", state.redacted_key)

    def test_reads_dotenv_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("OPENAI_API_KEY='sk-test123456'\n", encoding="utf-8")
            self.assertEqual(read_dotenv_key(path), "sk-test123456")

    def test_keyring_storage_is_used_without_exposing_secret(self):
        original = sys.modules.get("keyring")
        fake = FakeKeyringModule()
        sys.modules["keyring"] = fake
        try:
            stored = store_keyring_key("sk-test123456")
            self.assertTrue(stored["stored"])
            self.assertEqual(stored["redacted_key"], "sk-...3456")
            self.assertEqual(
                fake.values[(KEYRING_SERVICE, KEYRING_USERNAME)],
                "sk-test123456",
            )
            self.assertEqual(read_keyring_key(), "sk-test123456")
            state = resolve_auth_state(env={})
            self.assertEqual(state.status, AuthStatus.CONFIGURED_UNVERIFIED)
            self.assertEqual(state.source, "OS keyring")
            self.assertNotIn("test123456", state.redacted_key)
            deleted = delete_keyring_key()
            self.assertTrue(deleted["deleted"])
            self.assertIsNone(read_keyring_key())
        finally:
            if original is None:
                sys.modules.pop("keyring", None)
            else:
                sys.modules["keyring"] = original

    def test_keyring_absence_fails_without_plaintext_fallback(self):
        original = sys.modules.get("keyring")
        sys.modules.pop("keyring", None)
        try:
            stored = store_keyring_key("sk-test123456")
            self.assertFalse(stored["stored"])
            self.assertIsNone(stored["redacted_key"])
        finally:
            if original is not None:
                sys.modules["keyring"] = original

    def test_validate_openai_api_key_reports_verified_without_exposing_secret(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeHTTPResponse(200)

        state = validate_openai_api_key(
            "sk-test123456",
            source="unit-test",
            timeout_seconds=0.5,
            opener=opener,
        )
        self.assertEqual(state.status, AuthStatus.VERIFIED)
        self.assertEqual(state.source, "unit-test")
        self.assertEqual(state.redacted_key, "sk-...3456")
        self.assertNotIn("test123456", state.message)
        self.assertEqual(requests[0][0].full_url, "https://api.openai.com/v1/models")
        self.assertEqual(requests[0][0].headers["Authorization"], "Bearer sk-test123456")

    def test_validate_openai_api_key_reports_invalid_and_offline(self):
        def invalid_opener(_request, timeout=None):
            raise error.HTTPError(
                "https://api.openai.com/v1/models",
                401,
                "Unauthorized",
                {},
                None,
            )

        invalid = validate_openai_api_key(
            "sk-test123456",
            timeout_seconds=0.5,
            opener=invalid_opener,
        )
        self.assertEqual(invalid.status, AuthStatus.INVALID)
        self.assertNotIn("test123456", str(invalid))

        def offline_opener(_request, timeout=None):
            raise OSError("network unavailable")

        offline = validate_openai_api_key(
            "sk-test123456",
            timeout_seconds=0.5,
            opener=offline_opener,
        )
        self.assertEqual(offline.status, AuthStatus.OFFLINE)
        self.assertNotIn("test123456", str(offline))

    def test_validate_configured_auth_uses_resolved_credential(self):
        state = validate_configured_openai_auth(
            env={"OPENAI_API_KEY": "sk-test123456"},
            timeout_seconds=0.5,
            opener=lambda _request, timeout=None: FakeHTTPResponse(200),
        )
        self.assertEqual(state.status, AuthStatus.VERIFIED)
        self.assertEqual(state.source, "environment")


class TestVibeCADPreferences(unittest.TestCase):
    def setUp(self):
        self._pref = preferences()
        self._old_use_online = self._pref.GetBool("UseOnlineProvider", True)
        self._old_model = self._pref.GetString("Model", DEFAULT_MODEL)
        self._old_dotenv = self._pref.GetString("DotenvPath", "")
        self._old_disabled = self._pref.GetString("DisabledWorkbenches", "")
        self._old_reasoning_effort = self._pref.GetString(
            "ReasoningEffort",
            DEFAULT_REASONING_EFFORT,
        )
        self._old_allow_primitives = self._pref.GetBool("AllowPrimitiveProviderTools", False)

    def tearDown(self):
        save_settings(
            VibeCADSettings(
                use_online_provider=self._old_use_online,
                model=self._old_model,
                dotenv_path=self._old_dotenv,
                disabled_workbenches=tuple(
                    item
                    for item in self._old_disabled.split(",")
                    if item
                ),
                reasoning_effort=self._old_reasoning_effort,
                allow_primitive_provider_tools=self._old_allow_primitives,
            )
        )

    def test_preferences_persist_non_secret_settings(self):
        save_settings(
            VibeCADSettings(
                use_online_provider=False,
                model=DEFAULT_MODEL,
                dotenv_path="/tmp/vibecad-test.env",
                disabled_workbenches=("PartWorkbench", "SketcherWorkbench"),
                reasoning_effort="xhigh",
                allow_primitive_provider_tools=True,
            )
        )
        settings = load_settings()
        self.assertFalse(settings.use_online_provider)
        self.assertEqual(settings.model, DEFAULT_MODEL)
        self.assertEqual(settings.dotenv_path, "/tmp/vibecad-test.env")
        self.assertEqual(
            settings.disabled_workbenches,
            ("PartWorkbench", "SketcherWorkbench"),
        )
        self.assertEqual(settings.reasoning_effort, "xhigh")
        self.assertTrue(settings.allow_primitive_provider_tools)
        self.assertEqual(self._pref.GetString("OpenAIApiKey", ""), "")

    def test_preferences_reset_to_defaults(self):
        save_settings(VibeCADSettings(False, DEFAULT_MODEL, "/tmp/test.env", (), "low", True))
        reset_settings()
        settings = load_settings()
        self.assertTrue(settings.use_online_provider)
        self.assertEqual(settings.model, DEFAULT_MODEL)
        self.assertEqual(settings.dotenv_path, "")
        self.assertEqual(settings.disabled_workbenches, ())
        self.assertEqual(settings.reasoning_effort, DEFAULT_REASONING_EFFORT)
        self.assertFalse(settings.allow_primitive_provider_tools)

    def test_preferences_normalize_reasoning_effort(self):
        self.assertEqual(tuple(REASONING_EFFORTS), ("none", "minimal", "low", "medium", "high", "xhigh"))
        self.assertEqual(normalize_reasoning_effort("LOW"), "low")
        self.assertEqual(normalize_reasoning_effort("not-real"), DEFAULT_REASONING_EFFORT)

    def test_preferences_tool_pack_checklist_persists_disabled_workbenches(self):
        try:
            from PySide import QtCore, QtWidgets
        except Exception:
            self.skipTest("PySide unavailable")

        page = None
        try:
            app = QtWidgets.QApplication.instance()
            if app is None:
                self.skipTest("QApplication unavailable")
            page = PreferencesPage()
            save_settings(VibeCADSettings(disabled_workbenches=("PartWorkbench",)))
            page.loadSettings()
            checklist = page.form.findChild(QtWidgets.QListWidget, "VibeCADPrefToolPacks")
            self.assertIsNotNone(checklist)
            part_item = checklist.findItems("PartWorkbench", QtCore.Qt.MatchExactly)[0]
            draft_item = checklist.findItems("DraftWorkbench", QtCore.Qt.MatchExactly)[0]
            self.assertEqual(part_item.checkState(), QtCore.Qt.Unchecked)
            self.assertEqual(draft_item.checkState(), QtCore.Qt.Checked)
            draft_item.setCheckState(QtCore.Qt.Unchecked)
            page.saveSettings()
            if app:
                app.processEvents()
            self.assertEqual(
                load_settings().disabled_workbenches,
                ("DraftWorkbench", "PartWorkbench"),
            )
        finally:
            if page is not None:
                page.form.deleteLater()

    def test_preferences_api_key_controls_use_keyring_and_clear_secret(self):
        try:
            from PySide import QtWidgets
        except Exception:
            self.skipTest("PySide unavailable")

        original = sys.modules.get("keyring")
        fake = FakeKeyringModule()
        sys.modules["keyring"] = fake
        page = None
        try:
            app = QtWidgets.QApplication.instance()
            if app is None:
                self.skipTest("QApplication unavailable")
            page = PreferencesPage()
            page.loadSettings()
            page.api_key.setText("sk-test123456")
            save_button = page.form.findChild(QtWidgets.QPushButton, "VibeCADPrefSaveApiKey")
            validate_button = page.form.findChild(QtWidgets.QPushButton, "VibeCADPrefValidateAuth")
            logout_button = page.form.findChild(QtWidgets.QPushButton, "VibeCADPrefLogout")
            self.assertIsNotNone(save_button)
            self.assertIsNotNone(validate_button)
            self.assertIsNotNone(logout_button)

            save_button.click()
            if app:
                app.processEvents()

            self.assertEqual(page.api_key.text(), "")
            self.assertEqual(
                fake.values[(KEYRING_SERVICE, KEYRING_USERNAME)],
                "sk-test123456",
            )
            self.assertIn("OS keyring", page.status.text())
            self.assertIn("sk-...3456", page.status.text())
            self.assertNotIn("test123456", page.status.text())
            self.assertEqual(self._pref.GetString("OpenAIApiKey", ""), "")

            original_validate_configured = VibeCADPreferences.validate_configured_openai_auth
            try:
                VibeCADPreferences.validate_configured_openai_auth = lambda **_kwargs: types.SimpleNamespace(
                    status=AuthStatus.VERIFIED,
                    source="OS keyring",
                    redacted_key="sk-...3456",
                    message="OpenAI API key validated.",
                )
                validate_button.click()
                if app:
                    app.processEvents()
                self.assertIn("verified", page.status.text())
                self.assertIn("OS keyring", page.status.text())
                self.assertIn("sk-...3456", page.status.text())
                self.assertNotIn("test123456", page.status.text())
            finally:
                VibeCADPreferences.validate_configured_openai_auth = original_validate_configured

            original_validate_typed = VibeCADPreferences.validate_openai_api_key
            try:
                calls = []

                def fake_validate_typed(value, **_kwargs):
                    calls.append(value)
                    return types.SimpleNamespace(
                        status=AuthStatus.INVALID,
                        source="unsaved API key",
                        redacted_key="sk-...0000",
                        message="OpenAI credential validation failed with HTTP 401.",
                    )

                VibeCADPreferences.validate_openai_api_key = fake_validate_typed
                page.api_key.setText("sk-invalid0000")
                validate_button.click()
                if app:
                    app.processEvents()
                self.assertEqual(calls, ["sk-invalid0000"])
                self.assertEqual(page.api_key.text(), "")
                self.assertIn("invalid", page.status.text())
                self.assertIn("unsaved API key", page.status.text())
                self.assertIn("sk-...0000", page.status.text())
                self.assertNotIn("invalid0000", page.status.text())
            finally:
                VibeCADPreferences.validate_openai_api_key = original_validate_typed

            logout_button.click()
            if app:
                app.processEvents()

            self.assertNotIn((KEYRING_SERVICE, KEYRING_USERNAME), fake.values)
            self.assertEqual(page.api_key.text(), "")
            self.assertEqual(self._pref.GetString("OpenAIApiKey", ""), "")
        finally:
            if page is not None:
                page.form.deleteLater()
            if original is None:
                sys.modules.pop("keyring", None)
            else:
                sys.modules["keyring"] = original


class TestVibeCADTools(unittest.TestCase):
    def test_registry_rejects_duplicate_tool_names(self):
        registry = ToolRegistry()
        tool = VibeCADTool("core.test", "test", lambda: None, SafetyLevel.READ)
        registry.register(tool)
        with self.assertRaises(ValueError):
            registry.register(tool)

    def test_tool_schema_contains_safety_level(self):
        tool = VibeCADTool("core.test", "test", lambda: None, SafetyLevel.VIEW)
        self.assertEqual(tool.to_schema()["safety"], "view")


class TestVibeCADCore(unittest.TestCase):
    def setUp(self):
        self._old_settings = load_settings()
        save_settings(
            VibeCADSettings(
                use_online_provider=self._old_settings.use_online_provider,
                model=self._old_settings.model,
                dotenv_path=self._old_settings.dotenv_path,
                disabled_workbenches=self._old_settings.disabled_workbenches,
                reasoning_effort=self._old_settings.reasoning_effort,
                allow_primitive_provider_tools=True,
            )
        )

    def tearDown(self):
        save_settings(self._old_settings)

    def test_service_has_core_read_tools(self):
        service = VibeCADService()
        self.assertIn("core.get_active_document", service.registry.names())
        self.assertIn("core.get_selection", service.registry.names())
        self.assertIn("core.get_view_state", service.registry.names())
        self.assertIn("core.get_task_panel", service.registry.names())
        self.assertIn("core.wait_for_user_gui_action", service.registry.names())
        self.assertIn("core.capture_view_screenshot", service.registry.names())
        self.assertIn("core.get_report_view_errors", service.registry.names())
        self.assertIn("core.list_workbenches", service.registry.names())
        self.assertIn("core.list_registered_commands", service.registry.names())
        self.assertIn("core.list_active_workbench_commands", service.registry.names())
        self.assertIn("core.activate_workbench", service.registry.names())
        self.assertIn("core.get_active_workbench_tool_pack", service.registry.names())
        self.assertIn("core.list_workbench_tool_packs", service.registry.names())
        self.assertIn("core.list_workbench_object_templates", service.registry.names())
        self.assertIn("core.list_workbench_objects", service.registry.names())
        self.assertIn("core.get_object_properties", service.registry.names())
        self.assertNotIn("core.propose_create_part_box", service.registry.names())
        self.assertIn("core.run_workbench_command", service.registry.names())
        self.assertNotIn("core.propose_run_workbench_command", service.registry.names())
        self.assertNotIn("core.propose_create_workbench_object", service.registry.names())
        self.assertNotIn("core.propose_set_object_label", service.registry.names())
        self.assertIn("part.get_objects", service.registry.names())
        self.assertIn("part.create_primitive", service.registry.names())
        self.assertNotIn("part.propose_create_primitive", service.registry.names())
        self.assertIn("mesh.get_objects", service.registry.names())
        self.assertNotIn("mesh.propose_create_primitive", service.registry.names())
        self.assertIn("points.get_objects", service.registry.names())
        self.assertNotIn("points.propose_create_cloud", service.registry.names())
        self.assertIn("material.get_objects", service.registry.names())
        self.assertNotIn("material.propose_apply_appearance", service.registry.names())
        self.assertIn("sketcher.get_sketch", service.registry.names())
        self.assertIn("sketcher.create_sketch", service.registry.names())
        self.assertIn("sketcher.open_sketch", service.registry.names())
        self.assertIn("sketcher.close_sketch", service.registry.names())
        self.assertIn("sketcher.get_solver_status", service.registry.names())
        self.assertIn("sketcher.validate_profile", service.registry.names())
        self.assertIn("sketcher.validate_profile_deep", service.registry.names())
        self.assertIn("sketcher.diagnose_constraints", service.registry.names())
        self.assertIn("sketcher.list_geometry", service.registry.names())
        self.assertIn("sketcher.resolve_geometry", service.registry.names())
        self.assertIn("sketcher.set_geometry_name", service.registry.names())
        self.assertIn("sketcher.list_reference_geometry", service.registry.names())
        self.assertIn("sketcher.list_external_geometry", service.registry.names())
        self.assertIn("sketcher.add_line", service.registry.names())
        self.assertIn("sketcher.add_point", service.registry.names())
        self.assertIn("sketcher.add_polyline", service.registry.names())
        self.assertIn("sketcher.add_circle", service.registry.names())
        self.assertIn("sketcher.add_arc", service.registry.names())
        self.assertIn("sketcher.add_ellipse", service.registry.names())
        self.assertIn("sketcher.add_bspline", service.registry.names())
        self.assertIn("sketcher.add_slot", service.registry.names())
        self.assertIn("sketcher.add_constraint", service.registry.names())
        self.assertIn("sketcher.constrain_coincident", service.registry.names())
        self.assertIn("sketcher.constrain_horizontal", service.registry.names())
        self.assertIn("sketcher.constrain_vertical", service.registry.names())
        self.assertIn("sketcher.constrain_parallel", service.registry.names())
        self.assertIn("sketcher.constrain_perpendicular", service.registry.names())
        self.assertIn("sketcher.constrain_tangent", service.registry.names())
        self.assertIn("sketcher.constrain_equal", service.registry.names())
        self.assertIn("sketcher.constrain_distance", service.registry.names())
        self.assertIn("sketcher.constrain_distance_points", service.registry.names())
        self.assertIn("sketcher.constrain_distance_x", service.registry.names())
        self.assertIn("sketcher.constrain_distance_y", service.registry.names())
        self.assertIn("sketcher.constrain_angle_between", service.registry.names())
        self.assertIn("sketcher.constrain_lock_point", service.registry.names())
        self.assertIn("sketcher.constrain_block_geometry", service.registry.names())
        self.assertIn("sketcher.constrain_radius", service.registry.names())
        self.assertIn("sketcher.constrain_diameter", service.registry.names())
        self.assertIn("sketcher.constrain_point_on_object", service.registry.names())
        self.assertIn("sketcher.constrain_point_on_reference", service.registry.names())
        self.assertIn("sketcher.constrain_symmetric", service.registry.names())
        self.assertIn("sketcher.list_constraints", service.registry.names())
        self.assertIn("sketcher.get_constraint_by_name", service.registry.names())
        self.assertIn("sketcher.set_constraint_name", service.registry.names())
        self.assertIn("sketcher.set_constraint_value", service.registry.names())
        self.assertIn("sketcher.set_constraint_value_by_name", service.registry.names())
        self.assertIn("sketcher.set_constraint_driving", service.registry.names())
        self.assertIn("sketcher.set_constraint_expression", service.registry.names())
        self.assertIn("sketcher.move_point", service.registry.names())
        self.assertIn("sketcher.transform_geometry", service.registry.names())
        self.assertIn("sketcher.copy_geometry", service.registry.names())
        self.assertIn("sketcher.rectangular_array", service.registry.names())
        self.assertIn("sketcher.mirror_geometry", service.registry.names())
        self.assertIn("sketcher.offset_geometry", service.registry.names())
        self.assertIn("sketcher.trim_geometry", service.registry.names())
        self.assertIn("sketcher.extend_geometry", service.registry.names())
        self.assertIn("sketcher.split_geometry", service.registry.names())
        self.assertIn("sketcher.fillet_corner", service.registry.names())
        self.assertIn("sketcher.add_external_geometry", service.registry.names())
        self.assertIn("sketcher.remove_external_geometry", service.registry.names())
        self.assertIn("sketcher.delete_geometry", service.registry.names())
        self.assertIn("sketcher.delete_constraint", service.registry.names())
        self.assertIn("sketcher.delete_all_geometry", service.registry.names())
        self.assertIn("sketcher.delete_all_constraints", service.registry.names())
        self.assertIn("sketcher.set_construction", service.registry.names())
        self.assertIn("spreadsheet.get_sheet", service.registry.names())
        self.assertNotIn("spreadsheet.propose_set_cell", service.registry.names())
        self.assertIn("draft.get_objects", service.registry.names())
        self.assertNotIn("draft.propose_create_line", service.registry.names())
        self.assertIn("partdesign.get_bodies", service.registry.names())
        self.assertNotIn("partdesign.propose_create_body", service.registry.names())
        self.assertNotIn("partdesign.propose_add_box", service.registry.names())
        self.assertIn("techdraw.get_pages", service.registry.names())
        self.assertNotIn("techdraw.propose_create_page", service.registry.names())
        self.assertIn("fem.get_analyses", service.registry.names())
        self.assertNotIn("fem.propose_create_analysis", service.registry.names())
        self.assertIn("cam.get_jobs", service.registry.names())
        self.assertNotIn("cam.propose_create_job", service.registry.names())
        self.assertIn("bim.get_objects", service.registry.names())
        self.assertNotIn("bim.propose_create_container", service.registry.names())
        self.assertIn("assembly.get_assemblies", service.registry.names())
        self.assertIn("assembly.create_assembly", service.registry.names())
        self.assertNotIn("assembly.propose_create_assembly", service.registry.names())
        self.assertIn("inspection.get_objects", service.registry.names())
        self.assertNotIn("inspection.propose_create_inspection", service.registry.names())
        self.assertIn("openscad.get_objects", service.registry.names())
        self.assertNotIn("openscad.propose_import_csg", service.registry.names())
        self.assertIn("surface.get_objects", service.registry.names())
        self.assertNotIn("surface.propose_create_feature", service.registry.names())
        self.assertIn("reverseengineering.get_objects", service.registry.names())
        self.assertNotIn("reverseengineering.propose_approximate_curve", service.registry.names())
        self.assertIn("robot.get_objects", service.registry.names())
        self.assertNotIn("robot.propose_add_waypoint", service.registry.names())
        self.assertIn("meshpart.get_objects", service.registry.names())
        self.assertNotIn("meshpart.propose_tessellate_shape", service.registry.names())
        self.assertIn("core.list_pending_actions", service.registry.names())
        self.assertIn("core.apply_action", service.registry.names())
        self.assertIn("core.reject_action", service.registry.names())
        self.assertIn("core.undo_last_vibecad_action", service.registry.names())
        self.assertIn("core.clear_local_session", service.registry.names())

    def test_partdesign_tool_implementations_live_in_tool_modules(self):
        partdesign_modules = (
            "partdesign_create_sketch",
            "partdesign_pad_sketch",
            "partdesign_pocket_sketch",
            "partdesign_revolve_sketch",
            "partdesign_loft_profiles",
            "partdesign_sweep_profile",
            "partdesign_linear_pattern",
            "partdesign_polar_pattern",
            "partdesign_mirror_feature",
            "partdesign_fillet_feature",
            "partdesign_chamfer_feature",
            "partdesign_set_feature_dimensions",
            "partdesign_get_bodies",
        )
        for module_name in partdesign_modules:
            with self.subTest(module_name=module_name):
                module = importlib.import_module(f"tool_impl.service.{module_name}")
                self.assertTrue(callable(getattr(module, "run", None)))
                self.assertNotIn("handler", module.TOOL_SPEC)

        core_source = inspect.getsource(VibeCADService)
        self.assertNotIn("def create_partdesign_", core_source)
        self.assertNotIn("def propose_create_partdesign_body", core_source)
        self.assertNotIn("def propose_add_partdesign_box", core_source)

        register_source = inspect.getsource(VibeCADService._register_core_tools)
        self.assertIn("service_tools.register_tools(self._registry, self)", register_source)
        self.assertIn("sketcher_tools.register_tools(self._registry, self)", register_source)
        self.assertNotIn("VibeCADTool", register_source)

    def test_service_tools_all_have_module_run_entrypoints(self):
        from tool_impl import service as service_tools

        core_source = inspect.getsource(VibeCADService)
        self.assertNotIn("def propose_", core_source)
        registrar_source = inspect.getsource(service_tools.register_tools)
        self.assertNotIn("getattr(service", registrar_source)
        for module_name in service_tools.TOOL_MODULE_NAMES:
            with self.subTest(module_name=module_name):
                module = importlib.import_module(f"tool_impl.service.{module_name}")
                self.assertTrue(callable(getattr(module, "run", None)))
                self.assertNotIn("handler", module.TOOL_SPEC)
                module_source = inspect.getsource(module)
                self.assertNotIn("return service.propose_", module_source)
                if module_name != "core_apply_action":
                    self.assertNotRegex(
                        module_source,
                        r"return service\.(create_|add_|apply_|cut_|set_)",
                    )

    def test_service_tool_modules_do_not_delegate_back_to_core_tool_methods(self):
        from tool_impl import service as service_tools

        blocked_core_tool_methods = {
            "activate_workbench",
            "all_workbench_tool_packs",
            "apply_action",
            "assembly_summary",
            "bim_summary",
            "cam_summary",
            "capture_view_screenshot",
            "clear_local_session",
            "command_summary",
            "document_summary",
            "draft_summary",
            "fem_summary",
            "inspection_summary",
            "material_summary",
            "mesh_summary",
            "meshpart_summary",
            "object_property_summary",
            "openscad_summary",
            "part_summary",
            "partdesign_summary",
            "pending_actions",
            "points_summary",
            "reject_action",
            "report_tool_shape_gap",
            "report_view_errors",
            "reverseengineering_summary",
            "robot_summary",
            "run_workbench_command",
            "selection_summary",
            "spreadsheet_summary",
            "surface_summary",
            "task_panel_summary",
            "techdraw_summary",
            "tool_shape_report",
            "undo_last_vibecad_action",
            "view_state",
            "wait_for_user_gui_action",
            "workbench_command_summary",
            "workbench_object_summary",
            "workbench_object_templates",
            "workbench_summary",
            "workbench_tool_pack_summary",
        }
        pattern = re.compile(r"service\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\(")
        for module_name in service_tools.TOOL_MODULE_NAMES:
            module = importlib.import_module(f"tool_impl.service.{module_name}")
            module_source = inspect.getsource(module)
            leaked = sorted(
                {
                    match.group("name")
                    for match in pattern.finditer(module_source)
                    if match.group("name") in blocked_core_tool_methods
                }
            )
            self.assertEqual([], leaked, module_name)

    def test_service_tool_modules_do_not_use_shared_runtime_dispatchers(self):
        from tool_impl import service as service_tools

        service_dir = Path(__file__).resolve().parent / "tool_impl" / "service"
        self.assertFalse((service_dir / "core_runtime.py").exists())
        for module_name in service_tools.TOOL_MODULE_NAMES:
            module = importlib.import_module(f"tool_impl.service.{module_name}")
            module_source = inspect.getsource(module)
            self.assertNotIn("core_runtime", module_source, module_name)
            self.assertNotRegex(module_source, r"return\s+domain_runtime\.", module_name)

    def test_partdesign_extrude_tools_do_not_set_deprecated_midplane_property(self):
        for module_name in ("partdesign_pad_sketch", "partdesign_pocket_sketch"):
            with self.subTest(module_name=module_name):
                module = importlib.import_module(f"tool_impl.service.{module_name}")
                module_source = inspect.getsource(module)
                self.assertNotIn(".Midplane =", module_source)

    def test_context_summary_auth_is_json_safe(self):
        service = VibeCADService()
        auth = service.context_summary()["auth"]
        self.assertIsInstance(auth["status"], str)
        self.assertNotIn("redacted_key", auth)

    def test_context_summary_includes_provider_preferences(self):
        service = VibeCADService()
        provider = service.context_summary()["provider"]
        self.assertIn("model", provider)
        self.assertIn("reasoning_effort", provider)
        self.assertIn("use_online_by_default", provider)

    def test_provider_context_is_scoped_to_active_workbench_domains(self):
        service = VibeCADService()
        service.active_workbench_name = lambda: "PartDesignWorkbench"

        context = service.provider_context_summary()
        self.assertEqual(context["workbench"], "PartDesignWorkbench")
        self.assertIn("partdesign", context)
        self.assertIn("sketcher", context)
        self.assertIn("provider_tool_surface", context)
        self.assertEqual(
            context["provider_tool_surface"]["active_workbench"],
            "PartDesignWorkbench",
        )
        for unrelated in (
            "mesh",
            "points",
            "draft",
            "techdraw",
            "fem",
            "cam",
            "bim",
            "inspection",
            "openscad",
            "surface",
            "reverseengineering",
            "robot",
            "meshpart",
        ):
            self.assertNotIn(unrelated, context)

    def test_model_visible_context_uses_scoped_provider_context(self):
        service = VibeCADService()
        service.active_workbench_name = lambda: "PartDesignWorkbench"
        context = service.provider_context_summary()
        context["provider_tool_schemas"] = provider_safe_tool_schemas(
            service,
            "PartDesignWorkbench",
        )
        context["provider_tool_schemas_workbench"] = "PartDesignWorkbench"

        visible = _model_visible_context(context)
        self.assertIn("partdesign", visible)
        self.assertIn("sketcher", visible)
        self.assertNotIn("provider_tool_schemas", visible)
        self.assertNotIn("mesh", visible)
        self.assertNotIn("bim", visible)
        self.assertNotIn("robot", visible)

    def test_provider_api_key_reads_dotenv_without_exposing_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("OPENAI_API_KEY='sk-test123456'\n", encoding="utf-8")
            service = VibeCADService(dotenv_path=path)
            self.assertEqual(service.provider_api_key(), "sk-test123456")
            self.assertNotIn("sk-test123456", str(service.context_summary()))

    def test_provider_api_key_reads_preference_dotenv_without_exposing_context(self):
        old_settings = load_settings()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text("OPENAI_API_KEY='sk-test123456'\n", encoding="utf-8")
                save_settings(VibeCADSettings(dotenv_path=str(path)))
                service = VibeCADService()
                self.assertEqual(service.provider_api_key(), "sk-test123456")
                self.assertNotIn("sk-test123456", str(service.context_summary()))
        finally:
            save_settings(old_settings)

    def test_offline_provider_reports_context(self):
        result = OfflineProvider().run("hello", {"workbench": "SketcherWorkbench"})
        self.assertIn("SketcherWorkbench", result.final_output)

    def test_agents_input_from_context_keeps_text_when_no_screenshot_file(self):
        self.assertEqual(
            _agents_input_from_context(
                "plain prompt",
                {"view_screenshot": {"captured": True, "path": "/tmp/no-such-vibecad-image.png"}},
            ),
            "plain prompt",
        )

    def test_run_prompt_includes_provider_tool_schemas(self):
        service = VibeCADService()
        response = run_prompt("hello", service=service, prefer_online=False)
        self.assertEqual(response.provider, "OfflineProvider")
        self.assertNotIn("available_tools", response.context)
        self.assertIn("provider_tool_schemas", response.context)
        self.assertIn("core.get_active_document", str(response.context["provider_tool_schemas"]))
        self.assertIn("workbench_tool_pack", response.context)
        self.assertIn("workbench_commands", response.context)
        self.assertIn("workbench_object_templates", response.context)
        self.assertIn("workbench_objects", response.context)
        self.assertIn("provider_tool_scope", response.context)
        self.assertIn("active_tool_count", response.context["provider_tool_scope"])
        self.assertIn("active_tool_names", response.context["provider_tool_scope"])
        self.assertNotIn("omitted_tool_names", response.context["provider_tool_scope"])
        self.assertLessEqual(
            response.context["provider_tool_scope"]["active_tool_count"],
            response.context["provider_tool_scope"]["full_workbench_tool_count"],
        )
        visible = _model_visible_context(response.context)
        self.assertIn("provider_tool_scope", visible)
        self.assertNotIn("provider_tool_schemas", visible)
        self.assertNotIn("provider_tool_surface", visible)
        self.assertNotIn("omitted_tool_names", visible["provider_tool_scope"])
        if response.context.get("workbench") == "PartDesignWorkbench":
            self.assertIn("partdesign", response.context)
            self.assertIn("sketcher", response.context)
        self.assertNotIn("available_tools", response.context)
        self.assertIn("provider_tool_surface", response.context)
        self.assertIn("view_screenshot", response.context)
        self.assertIn("task_panel", response.context)
        self.assertIn("report_view_errors", response.context)

    def test_run_prompt_does_not_fake_offline_response_after_provider_failure(self):
        class FailingProvider(BaseProvider):
            def run(self, prompt, context, tool_runner=None):
                raise ProviderUnavailable("configured provider failed")

        service = VibeCADService()
        response = run_prompt("hello", service=service, provider=FailingProvider())
        self.assertEqual(response.provider, "FailingProvider")
        self.assertEqual(response.error, "configured provider failed")
        self.assertIn("configured provider failed", response.final_output)
        self.assertNotIn("OfflineProvider", response.final_output)

    def test_run_prompt_cancel_before_provider_turn_does_not_call_provider(self):
        class CountingProvider(BaseProvider):
            def __init__(self):
                self.calls = 0

            def run(self, prompt, context, tool_runner=None, cancellation_check=None):
                self.calls += 1
                return ProviderResult("should not run")

        events = []
        provider = CountingProvider()
        response = run_prompt(
            "hello",
            service=VibeCADService(),
            provider=provider,
            cancellation_check=lambda: True,
            progress_callback=events.append,
        )

        self.assertEqual(provider.calls, 0)
        self.assertIn("stopped by user", response.final_output)
        self.assertTrue(
            any(event.get("event") == "provider_run_cancelled" for event in events)
        )

    def test_model_visible_context_hides_internal_tool_menu(self):
        visible = _model_visible_context(
            {
                "workbench": "PartDesignWorkbench",
                "available_tools": [{"name": "partdesign.create_sketch"}],
                "available_tools_workbench": "PartDesignWorkbench",
                "provider_tool_schemas": [{"name": "partdesign.create_sketch"}],
                "provider_tool_schemas_workbench": "PartDesignWorkbench",
                "provider_function_tools": [
                    {
                        "tool_name": "partdesign.create_sketch",
                        "function_name": "partdesign_create_sketch",
                    }
                ],
                "provider_tool_surface": {"tools": ["partdesign.create_sketch"]},
                "tool_shape_report": {"provider_visible_tool_count": 1},
            }
        )
        self.assertNotIn("available_tools", visible)
        self.assertNotIn("available_tools_workbench", visible)
        self.assertNotIn("provider_tool_schemas", visible)
        self.assertNotIn("provider_tool_schemas_workbench", visible)
        self.assertNotIn("provider_function_tools", visible)
        self.assertNotIn("provider_tool_surface", visible)
        self.assertNotIn("tool_shape_report", visible)

    def test_result_summary_includes_native_transaction_failure_details(self):
        summary = _result_summary(
            {
                "ok": False,
                "transaction": {
                    "ok": False,
                    "error": "native mirror failed",
                    "report_view_errors": {
                        "captured": True,
                        "errors": ["native mirror failed"],
                    },
                    "document_delta": {"object_count_delta": 0},
                },
            }
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["transaction_error"], "native mirror failed")
        self.assertIn("native mirror failed", str(summary["transaction_report_view_errors"]))
        self.assertEqual(summary["transaction_document_delta"]["object_count_delta"], 0)

        nested_summary = _result_summary(
            {
                "ok": False,
                "result": {
                    "ok": False,
                    "transaction": {
                        "ok": False,
                        "error": "native revolve failed",
                        "document_delta": {"object_count_delta": 1},
                    },
                },
            }
        )
        self.assertEqual(nested_summary["transaction_error"], "native revolve failed")
        self.assertEqual(nested_summary["transaction_document_delta"]["object_count_delta"], 1)

    def test_report_view_error_filter_ignores_vibecad_progress_noise(self):
        self.assertFalse(_is_report_view_error_line("Report errors: 12"))
        self.assertFalse(_is_report_view_error_line("No report-view errors detected."))
        self.assertFalse(
            _is_report_view_error_line(
                '23:05:13  {"progress": {"event": "tool_call_completed", "ok": true}}'
            )
        )
        self.assertTrue(_is_report_view_error_line("Traceback: native sketch solver failed"))
        self.assertTrue(_is_report_view_error_line("PartDesign error: pocket failed"))
        self.assertEqual(
            _bounded_report_view_line("x" * 600),
            ("x" * 497) + "...",
        )

    def test_result_summary_includes_assembly_payload(self):
        summary = _result_summary(
            {
                "ok": True,
                "result": {
                    "ok": True,
                    "assembly": "Assembly",
                    "assembly_label": "Fixture Assembly",
                    "component": "BasePlate",
                    "component_label": "Base Plate",
                    "components": 2,
                    "components_added": ["BasePlate", "Jaw"],
                    "missing_components": [],
                    "already_present": False,
                    "assembly_summary": {
                        "assembly_count": 1,
                        "assemblies": [{"label": "Fixture Assembly", "components": 2}],
                    },
                },
            }
        )

        self.assertEqual(summary["assembly_label"], "Fixture Assembly")
        self.assertEqual(summary["component_label"], "Base Plate")
        self.assertEqual(summary["components"], 2)
        self.assertEqual(summary["components_added"], ["BasePlate", "Jaw"])
        self.assertEqual(summary["assembly_summary"]["assembly_count"], 1)

    def test_failed_transaction_includes_document_delta(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADFailedTransactionDeltaTest")
        try:
            def _fail_after_object():
                doc.addObject("App::DocumentObjectGroup", "FailedCreatedObject")
                raise RuntimeError("intentional native failure")

            result = run_freecad_transaction("Fail after object", _fail_after_object)

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "intentional native failure")
            self.assertIn("document_delta", result)
            self.assertGreaterEqual(result["document_delta"]["object_count_delta"], 0)
            created_names = {
                item["name"]
                for item in result["document_delta"].get("created_objects", [])
            }
            if doc.getObject("FailedCreatedObject") is not None:
                self.assertIn("FailedCreatedObject", created_names)
        finally:
            App.closeDocument(doc.Name)

    def test_transaction_document_delta_includes_shape_changes(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTransactionShapeDeltaTest")
        try:
            box = doc.addObject("Part::Box", "ShapeDeltaBox")
            box.Length = 10
            box.Width = 10
            box.Height = 10
            doc.recompute()

            def _change_shape():
                box.Length = 20
                doc.recompute()
                return {"box": box.Name}

            result = run_freecad_transaction("Change box shape", _change_shape)

            self.assertTrue(result["ok"], result)
            changed = {
                item["name"]: item
                for item in result["document_delta"].get("changed_objects", [])
            }
            self.assertIn("ShapeDeltaBox", changed)
            before_shape = changed["ShapeDeltaBox"]["before"]["shape"]
            after_shape = changed["ShapeDeltaBox"]["after"]["shape"]
            self.assertAlmostEqual(before_shape["volume"], 1000.0)
            self.assertAlmostEqual(after_shape["volume"], 2000.0)
        finally:
            App.closeDocument(doc.Name)

    def test_transaction_snapshot_omits_app_datum_shapes(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTransactionDatumShapeFilterTest")
        try:
            plane = doc.addObject("App::Plane", "DatumPlane")
            box = doc.addObject("Part::Box", "RealBox")
            box.Length = 10
            box.Width = 10
            box.Height = 10
            doc.recompute()

            def _change_shape():
                box.Height = 12
                doc.recompute()
                return {"box": box.Name, "plane": plane.Name}

            result = run_freecad_transaction("Filter datum shapes", _change_shape)

            self.assertTrue(result["ok"], result)
            after = {
                item["name"]: item
                for item in result["document_after"].get("objects", [])
            }
            self.assertNotIn("shape", after["DatumPlane"])
            self.assertIn("shape", after["RealBox"])
        finally:
            App.closeDocument(doc.Name)

    def test_result_summary_preserves_partdesign_feature_effect(self):
        summary = _result_summary(
            {
                "ok": True,
                "result": {
                    "active_feature": "Pad",
                    "feature_effect": {
                        "ok": True,
                        "operation": "pad",
                        "body_shape_delta": {"volume_delta": 100.0},
                    },
                    "feature_shape": {"available": True, "faces": 6, "volume": 100.0},
                    "body_shape_delta": {"volume_delta": 100.0},
                    "rolled_back_feature": True,
                    "body_shape_after_rollback": {
                        "available": True,
                        "faces": 6,
                        "volume": 100.0,
                    },
                },
            }
        )

        self.assertTrue(summary["feature_effect"]["ok"])
        self.assertEqual(summary["body_shape_delta"]["volume_delta"], 100.0)
        self.assertTrue(summary["rolled_back_feature"])
        self.assertEqual(summary["body_shape_after_rollback"]["volume"], 100.0)

    def test_openai_provider_request_uses_precise_function_tools_not_generic_dispatcher(self):
        from provider_tools import create_tool

        class FakeFunctionTool:
            def __init__(
                self,
                name,
                description,
                params_json_schema,
                on_invoke_tool,
                strict_json_schema,
            ):
                self.name = name
                self.description = description
                self.params_json_schema = params_json_schema
                self.on_invoke_tool = on_invoke_tool
                self.strict_json_schema = strict_json_schema

        class FakeConn:
            def send(self, _message):
                raise AssertionError("tool should not be invoked while building request schema")

        service = VibeCADService()
        schemas = provider_safe_tool_schemas(service, "PartDesignWorkbench")
        selected_names = {
            "core.get_active_document",
            "partdesign.create_sketch",
            "sketcher.draw_rectangle",
            "partdesign.pad_sketch",
        }
        selected = [schema for schema in schemas if schema["name"] in selected_names]
        self.assertEqual({schema["name"] for schema in selected}, selected_names)

        request_tools = [
            _provider_tool_request_schema(create_tool(schema, FakeConn(), FakeFunctionTool))
            for schema in selected
        ]
        function_names = {tool["function_name"] for tool in request_tools}
        self.assertEqual(
            function_names,
            {
                "core_get_active_document",
                "partdesign_create_sketch",
                "sketcher_draw_rectangle",
                "partdesign_pad_sketch",
            },
        )
        self.assertNotIn("execute_vibecad_tool", function_names)
        for tool in request_tools:
            self.assertTrue(tool["callable"], tool)
            self.assertIsInstance(tool["description"], str)
            self.assertIn("Native VibeCAD tool:", tool["description"])
            self.assertIsInstance(tool["params_json_schema"], dict)
            self.assertEqual(tool["params_json_schema"]["type"], "object")
            self.assertIn("properties", tool["params_json_schema"])

    def test_openai_request_tool_list_uses_active_scoped_surface(self):
        class FakeFunctionTool:
            def __init__(
                self,
                name,
                description,
                params_json_schema,
                on_invoke_tool,
                strict_json_schema,
            ):
                self.name = name
                self.description = description
                self.params_json_schema = params_json_schema
                self.on_invoke_tool = on_invoke_tool
                self.strict_json_schema = strict_json_schema

        class FakeConn:
            def send(self, _message):
                raise AssertionError("tool should not be invoked while building request schema")

        service = VibeCADService()
        full = provider_safe_tool_schemas(service, "PartDesignWorkbench")
        scope = provider_tool_scope_for_context(service, "PartDesignWorkbench")
        scoped = provider_safe_tool_schemas(
            service,
            "PartDesignWorkbench",
            tool_names=scope.tool_names,
        )
        context = {"provider_tool_schemas": scoped}

        provider_tools = _build_provider_function_tools(context, FakeConn(), FakeFunctionTool)
        request_tools = [_provider_tool_request_schema(tool) for tool in provider_tools]
        function_names = {tool["function_name"] for tool in request_tools}

        self.assertEqual(scope.phase, "partdesign_setup")
        self.assertEqual(len(request_tools), len(scoped))
        self.assertLess(len(request_tools), len(full))
        self.assertIn("partdesign_create_body", function_names)
        self.assertIn("partdesign_create_sketch", function_names)
        self.assertNotIn("sketcher_add_line", function_names)
        self.assertNotIn("partdesign_pad_sketch", function_names)
        self.assertNotIn("execute_vibecad_tool", function_names)
        self.assertEqual(len(context["provider_function_tools"]), len(scoped))

    def test_provider_context_tool_is_explicit_module_backed_function_tool(self):
        from provider_tools import create_context_tool, registered_tool_names

        class FakeFunctionTool:
            def __init__(
                self,
                name,
                description,
                params_json_schema,
                on_invoke_tool,
                strict_json_schema,
            ):
                self.name = name
                self.description = description
                self.params_json_schema = params_json_schema
                self.on_invoke_tool = on_invoke_tool
                self.strict_json_schema = strict_json_schema

        schema = {
            "name": "core.get_current_freecad_context",
            "parameters": {"type": "object", "properties": {}},
            "workbench": "global",
            "safety": "read",
        }
        tool = create_context_tool(
            schema,
            {
                "workbench": "PartDesignWorkbench",
                "available_tools": [{"name": "part.create_primitive"}],
                "available_tools_workbench": "PartWorkbench",
                "provider_tool_schemas": [{"name": "part.create_primitive"}],
                "provider_function_tools": [
                    {"tool_name": "core.get_active_document", "function_name": "core_get_active_document"}
                ],
            },
            FakeFunctionTool,
        )

        self.assertIn("core.get_current_freecad_context", registered_tool_names())
        request_schema = _provider_tool_request_schema(tool)
        self.assertEqual(request_schema["function_name"], "core_get_current_freecad_context")
        self.assertTrue(request_schema["callable"])
        self.assertIn("not a generic CAD operation router", request_schema["description"])

    def test_openai_provider_has_no_inline_function_tool_context_helper(self):
        import VibeCADProvider

        source = inspect.getsource(VibeCADProvider)
        self.assertNotIn("@function_tool", source)
        self.assertIn("create_context_tool", source)

    def test_partdesign_execution_contract_requires_constrained_sketch_feature_order(self):
        contract = _execution_contract_for_context({"workbench": "PartDesignWorkbench"})
        self.assertEqual(contract["mode"], "parametric_partdesign")
        required_order = " ".join(contract["required_order"])
        self.assertIn("create sketch", required_order)
        self.assertIn("fully constrain", required_order)
        self.assertIn("DoF is 0", required_order)
        self.assertIn("native PartDesign features", required_order)
        gates = " ".join(contract["completion_gates"])
        self.assertIn("under-constrained", gates)
        self.assertIn("Part primitive substitutes", gates)

    def test_openai_request_dump_writes_full_provider_payload(self):
        old_dump_dir = os.environ.get("VIBECAD_OPENAI_REQUEST_DUMP_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["VIBECAD_OPENAI_REQUEST_DUMP_DIR"] = directory
                path = _write_openai_request_dump(
                    {
                        "schema": "vibecad-openai-agents-request-v1",
                        "model": DEFAULT_MODEL,
                        "agent": {
                            "instructions": "full system instructions",
                            "tools": [
                                {
                                    "function_name": "partdesign_create_sketch",
                                    "params_json_schema": {
                                        "type": "object",
                                        "properties": {"plane": {"type": "string"}},
                                    },
                                }
                            ],
                        },
                        "run": {"input": "make a 10mm square"},
                    }
                )
                self.assertIsNotNone(path)
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(data["model"], DEFAULT_MODEL)
                self.assertEqual(data["agent"]["instructions"], "full system instructions")
                self.assertEqual(
                    data["agent"]["tools"][0]["function_name"],
                    "partdesign_create_sketch",
                )
                self.assertEqual(data["run"]["input"], "make a 10mm square")
                latest = Path(directory) / "latest-openai-request.json"
                self.assertTrue(latest.is_file())
                latest_data = json.loads(latest.read_text(encoding="utf-8"))
                self.assertEqual(latest_data["schema"], "vibecad-openai-agents-request-v1")
        finally:
            if old_dump_dir is None:
                os.environ.pop("VIBECAD_OPENAI_REQUEST_DUMP_DIR", None)
            else:
                os.environ["VIBECAD_OPENAI_REQUEST_DUMP_DIR"] = old_dump_dir

    def test_live_provider_acceptance_covers_required_goal_categories(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        scenarios = data["SCENARIOS"]
        requirements_for = data["_requirements_for_scenario"]
        completion_directive = data["COMPLETION_DIRECTIVE"]
        expected = {
            "mechanical",
            "partdesign",
            "robot",
            "drone",
            "automotive",
            "aerospace",
            "marine",
            "enclosure",
            "assembly",
            "documentation",
            "rocket_engine",
        }
        self.assertTrue(expected.issubset(set(scenarios)))
        for scenario in expected:
            self.assertIn(completion_directive, scenarios[scenario])
            requirements = requirements_for(scenario)
            self.assertGreaterEqual(int(requirements["minimum_objects"]), 3)
            self.assertGreaterEqual(int(requirements["minimum_mutating_tools"]), 6)
            self.assertIn("sketcher.", requirements["required_tool_prefixes"])
            self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        assembly_requirements = requirements_for("assembly")
        self.assertGreaterEqual(int(assembly_requirements["minimum_assemblies"]), 1)
        self.assertGreaterEqual(int(assembly_requirements["minimum_assembly_components"]), 2)
        self.assertIn("assembly.", assembly_requirements["required_tool_prefixes"])
        self.assertIn("intentionally bounded", scenarios["revision"])
        self.assertIn("revised in the next prompt", scenarios["revision"])
        documentation_requirements = requirements_for("documentation")
        self.assertGreaterEqual(int(documentation_requirements["minimum_techdraw_pages"]), 1)
        self.assertGreaterEqual(int(documentation_requirements["minimum_techdraw_views"]), 1)
        self.assertIn("techdraw.", documentation_requirements["required_tool_prefixes"])
        self.assertIn("TechDraw drawing page", scenarios["documentation"])

    def test_live_provider_acceptance_reports_request_dump_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        old_dump_dir = os.environ.get("VIBECAD_OPENAI_REQUEST_DUMP_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["VIBECAD_OPENAI_REQUEST_DUMP_DIR"] = directory
                data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
                latest = Path(directory) / "latest-openai-request.json"
                latest.write_text(
                    json.dumps(
                        {
                            "schema": "vibecad-openai-agents-request-v1",
                            "model": DEFAULT_MODEL,
                            "agent": {"tools": [{"function_name": "core_get_active_document"}]},
                            "model_visible_context": {"workbench": "PartDesignWorkbench"},
                        }
                    ),
                    encoding="utf-8",
                )
                summary = data["_latest_request_dump_summary"]()
                self.assertTrue(summary["exists"])
                self.assertEqual(summary["schema"], "vibecad-openai-agents-request-v1")
                self.assertEqual(summary["model"], DEFAULT_MODEL)
                self.assertEqual(summary["tool_count"], 1)
                self.assertTrue(summary["has_model_visible_context"])
                self.assertFalse(summary["has_generic_dispatcher"])
                self.assertFalse(summary["has_available_tools"])
                self.assertFalse(summary["has_tool_menu_context"])
                self.assertEqual(summary["proposal_or_queue_functions"], [])

                latest.write_text(
                    json.dumps(
                        {
                            "schema": "vibecad-openai-agents-request-v1",
                            "model": DEFAULT_MODEL,
                            "agent": {
                                "tools": [
                                    {"function_name": "execute_vibecad_tool"},
                                    {"function_name": "core_apply_action"},
                                    {"function_name": "legacy_queue_apply"},
                                ]
                            },
                            "model_visible_context": {
                                "workbench": "PartDesignWorkbench",
                                "available_tools": [{"name": "partdesign.create_sketch"}],
                                "provider_function_tools": ["partdesign_create_sketch"],
                                "provider_tool_surface": {"tools": ["partdesign.create_sketch"]},
                                "tool_shape_report": {"provider_visible_tool_count": 1},
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                bad_summary = data["_latest_request_dump_summary"]()
                self.assertTrue(bad_summary["has_generic_dispatcher"])
                self.assertTrue(bad_summary["has_available_tools"])
                self.assertTrue(bad_summary["has_tool_menu_context"])
                self.assertEqual(
                    bad_summary["proposal_or_queue_functions"],
                    ["core_apply_action"],
                )
        finally:
            if old_dump_dir is None:
                os.environ.pop("VIBECAD_OPENAI_REQUEST_DUMP_DIR", None)
            else:
                os.environ["VIBECAD_OPENAI_REQUEST_DUMP_DIR"] = old_dump_dir

    def test_live_provider_acceptance_rejects_unresolved_final_output(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        reasons = data["_final_output_unresolved_reasons"](
            "Current status: attempted pockets were created, but the body volume "
            "remained unchanged and the cutouts were not actually cutting the web. "
            "Next step after refresh: recreate them."
        )
        self.assertIn("ineffective-geometry", reasons)
        self.assertIn("next-step", reasons)

    def test_live_provider_acceptance_rejects_timeout_final_output(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        reasons = data["_final_output_unresolved_reasons"](
            "The autonomous provider loop reached the configured 600 second "
            "limit before completion."
        )
        self.assertIn("timeout", reasons)

    def test_live_provider_acceptance_allows_prior_checkpoint_before_completion(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        reasons = data["_final_output_unresolved_reasons"](
            "Progress checkpoint: I will continue after refresh. "
            "Completed a coherent first-pass aerospace wing-rib CAD model. "
            "Captured and inspected the viewport screenshot; the model is visible."
        )
        self.assertEqual([], reasons)

    def test_live_provider_acceptance_detects_ineffective_partdesign_features(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        ineffective = data["_ineffective_partdesign_features"](
            [
                {
                    "tool_name": "partdesign.pocket_sketch",
                    "ok": True,
                    "result": {
                        "active_feature": "Pocket",
                        "feature_effect": {
                            "ok": False,
                            "operation": "pocket",
                            "body_shape_delta": {"volume_delta": 0.0},
                        },
                    },
                },
                {
                    "tool_name": "partdesign.draft_feature",
                    "ok": True,
                    "result": {
                        "active_feature": "Draft",
                        "feature_effect": {
                            "ok": False,
                            "operation": "draft",
                            "body_shape_delta": {"volume_delta": 0.0},
                        },
                    },
                },
                {
                    "tool_name": "partdesign.get_bodies",
                    "ok": True,
                    "result": {"body_count": 1},
                },
                {
                    "tool_name": "partdesign.hole_from_sketch",
                    "ok": True,
                    "result": {
                        "active_feature": "Hole",
                        "feature_effect": {
                            "ok": True,
                            "operation": "hole",
                            "body_shape_delta": {"volume_delta": -100.0},
                        },
                    },
                },
            ]
        )
        self.assertEqual(len(ineffective), 2)
        self.assertEqual(ineffective[0]["feature"], "Pocket")
        self.assertEqual(ineffective[1]["tool_name"], "partdesign.draft_feature")
        self.assertEqual(ineffective[1]["feature"], "Draft")

    def test_live_provider_acceptance_ignores_deleted_ineffective_partdesign_features(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        ineffective = data["_ineffective_partdesign_features"](
            [
                {
                    "tool_name": "partdesign.pocket_sketch",
                    "ok": False,
                    "result": {
                        "active_feature": "Pocket",
                        "feature_effect": {
                            "ok": False,
                            "operation": "pocket",
                            "body_shape_delta": {"volume_delta": 0.0},
                        },
                    },
                },
                {
                    "tool_name": "core.delete_object",
                    "ok": True,
                    "result": {
                        "transaction_document_delta": {
                            "deleted_objects": [
                                {"name": "Pocket", "type": "PartDesign::Pocket"}
                            ]
                        }
                    },
                },
                {
                    "tool_name": "partdesign.pocket_sketch",
                    "ok": True,
                    "result": {
                        "active_feature": "Pocket",
                        "feature_effect": {
                            "ok": True,
                            "operation": "pocket",
                            "body_shape_delta": {"volume_delta": -50.0},
                        },
                    },
                },
            ]
        )
        self.assertEqual([], ineffective)

    def test_live_provider_acceptance_ignores_rolled_back_ineffective_partdesign_features(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        ineffective = data["_ineffective_partdesign_features"](
            [
                {
                    "tool_name": "partdesign.pad_sketch",
                    "ok": False,
                    "result": {
                        "active_feature": "Pad",
                        "rolled_back_feature": True,
                        "feature_effect": {
                            "ok": False,
                            "operation": "pad",
                            "body_shape_delta": {"volume_delta": 0.0},
                        },
                    },
                }
            ]
        )
        self.assertEqual([], ineffective)

    def test_live_provider_robot_acceptance_requires_multipart_assembly_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("robot")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 2)
        self.assertGreaterEqual(requirements["minimum_assemblies"], 1)
        self.assertGreaterEqual(requirements["minimum_assembly_components"], 2)
        self.assertIn("assembly.", requirements["required_tool_prefixes"])

        evidence = data["_partdesign_evidence"](
            {
                "body_count": 1,
                "bodies": [
                    {
                        "features": [
                            {"type": "Sketcher::SketchObject"},
                            {"type": "PartDesign::Pad"},
                            {"type": "PartDesign::Body"},
                        ]
                    }
                ],
            }
        )
        self.assertEqual(evidence["body_count"], 1)
        self.assertEqual(evidence["feature_count"], 3)
        self.assertEqual(evidence["native_feature_count"], 1)

    def test_live_provider_drone_acceptance_requires_multipart_assembly_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("drone")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 2)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 4)
        self.assertGreaterEqual(requirements["minimum_assemblies"], 1)
        self.assertGreaterEqual(requirements["minimum_assembly_components"], 2)
        self.assertIn("assembly.", requirements["required_tool_prefixes"])

    def test_live_provider_automotive_acceptance_requires_complex_partdesign_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("automotive")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 1)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 4)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])

    def test_live_provider_aerospace_acceptance_requires_complex_partdesign_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("aerospace")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 1)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 4)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])

    def test_live_provider_marine_acceptance_requires_complex_partdesign_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("marine")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 1)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 4)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])

    def test_live_provider_enclosure_acceptance_requires_multipart_assembly_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("enclosure")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 2)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 5)
        self.assertGreaterEqual(requirements["minimum_assemblies"], 1)
        self.assertGreaterEqual(requirements["minimum_assembly_components"], 2)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])
        self.assertIn("assembly.", requirements["required_tool_prefixes"])

    def test_live_provider_mechanical_acceptance_requires_complex_partdesign_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("mechanical")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 1)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 4)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])

    def test_live_provider_documentation_acceptance_requires_techdraw_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("documentation")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 1)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 3)
        self.assertGreaterEqual(requirements["minimum_techdraw_pages"], 1)
        self.assertGreaterEqual(requirements["minimum_techdraw_views"], 1)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])
        self.assertIn("techdraw.", requirements["required_tool_prefixes"])
        evidence = data["_techdraw_evidence"](
            {
                "page_count": 1,
                "pages": [
                    {
                        "views": [
                            {"source_count": 1},
                            {"source_count": 0},
                        ]
                    }
                ],
            }
        )
        self.assertEqual(evidence["page_count"], 1)
        self.assertEqual(evidence["view_count"], 2)
        self.assertEqual(evidence["sourced_view_count"], 1)

    def test_live_provider_rocket_engine_acceptance_requires_complex_assembly_evidence(self):
        script = _repo_tool_script("vibecad_live_provider_acceptance.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_provider_acceptance_test")
        requirements = data["_requirements_for_scenario"]("rocket_engine")
        self.assertGreaterEqual(requirements["minimum_partdesign_bodies"], 3)
        self.assertGreaterEqual(requirements["minimum_partdesign_features"], 6)
        self.assertGreaterEqual(requirements["minimum_assemblies"], 1)
        self.assertGreaterEqual(requirements["minimum_assembly_components"], 3)
        self.assertIn("partdesign.", requirements["required_tool_prefixes"])
        self.assertIn("sketcher.", requirements["required_tool_prefixes"])
        self.assertIn("assembly.", requirements["required_tool_prefixes"])

        scenarios = data["SCENARIOS"]
        self.assertIn("multiple named PartDesign component bodies", scenarios["rocket_engine"])
        self.assertIn("at least six surviving native PartDesign features", scenarios["rocket_engine"])

    def test_live_acceptance_matrix_defaults_cover_full_goal_matrix(self):
        script = _repo_tool_script("vibecad_live_acceptance_matrix.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_acceptance_matrix_test")
        scenarios = set(data["DEFAULT_SCENARIOS"])
        self.assertTrue(
            {
                "mechanical",
                "partdesign",
                "robot",
                "drone",
                "automotive",
                "aerospace",
                "marine",
                "enclosure",
                "assembly",
                "documentation",
                "rocket_engine",
            }.issubset(scenarios)
        )

    def test_live_acceptance_matrix_preserves_timeout_partial_evidence(self):
        script = _repo_tool_script("vibecad_live_acceptance_matrix.py")
        data = runpy.run_path(str(script), run_name="vibecad_live_acceptance_matrix_test")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            progress = base / "progress.jsonl"
            request_dumps = base / "request-dumps"
            request_dumps.mkdir()
            progress.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event": "tool_call_completed",
                                "tool_name": "partdesign.create_sketch",
                                "ok": True,
                                "safety": "safe_write",
                                "result": {
                                    "transaction_document_delta": {
                                        "object_count_after": 10,
                                    }
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "event": "tool_call_completed",
                                "tool_name": "core.capture_view_screenshot",
                                "ok": True,
                                "safety": "view",
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            (request_dumps / "latest-openai-request.json").write_text(
                json.dumps(
                    {
                        "schema": "vibecad-openai-agents-request-v1",
                        "agent": {"tools": [{"function_name": "partdesign_create_sketch"}]},
                        "model_visible_context": {"workbench": "PartDesignWorkbench"},
                    }
                ),
                encoding="utf-8",
            )

            result = data["_partial_result_from_progress"](
                "mechanical",
                progress,
                request_dumps,
                "matrix process timeout after 1 seconds",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["partial_evidence"])
        self.assertEqual(result["tool_count"], 2)
        self.assertEqual(result["mutating_tool_count"], 1)
        self.assertEqual(result["object_count"], 10)
        self.assertTrue(result["screenshot_captured"])
        self.assertEqual(result["request_dump"]["schema"], "vibecad-openai-agents-request-v1")
        summary = data["_scenario_summary"](
            "mechanical",
            {"ok": True, "provider_timeout_event_count": 2, "request_dump": result["request_dump"]},
            1.0,
            0,
        )
        self.assertEqual(summary["provider_timeout_event_count"], 2)

    def test_conversation_history_is_scoped_to_active_document(self):
        import FreeCAD as App

        for existing in list(App.listDocuments().values()):
            App.closeDocument(existing.Name)
        service = VibeCADService()
        with tempfile.TemporaryDirectory() as tmp:
            doc_one = App.newDocument("VibeCADScopedConversationOne")
            try:
                doc_one.saveAs(str(Path(tmp) / "scoped-one.FCStd"))
                service.record_conversation_turn("user", "only document one should know this")
                first_history = service.conversation_history()
                self.assertEqual(first_history["scope"]["kind"], "saved_document")
                self.assertEqual(first_history["turn_count"], 1)
                self.assertIn("scoped-one.FCStd", first_history["scope"]["file_path"])

                doc_two = App.newDocument("VibeCADScopedConversationTwo")
                doc_two.saveAs(str(Path(tmp) / "scoped-two.FCStd"))
                App.setActiveDocument(doc_two.Name)
                second_history = service.conversation_history()
                self.assertEqual(second_history["scope"]["kind"], "saved_document")
                self.assertEqual(second_history["conversation"], [])
                self.assertNotIn(
                    "only document one should know this",
                    json.dumps(service.context_summary()["conversation"]),
                )

                App.setActiveDocument(doc_one.Name)
                reloaded = service.conversation_history()
                self.assertEqual(reloaded["turn_count"], 1)
                self.assertEqual(
                    reloaded["conversation"][0]["content"],
                    "only document one should know this",
                )
            finally:
                for document in list(App.listDocuments().values()):
                    App.closeDocument(document.Name)

    def test_unsaved_conversation_history_does_not_leak_between_documents(self):
        import FreeCAD as App

        for existing in list(App.listDocuments().values()):
            App.closeDocument(existing.Name)
        service = VibeCADService()
        doc_one = App.newDocument("VibeCADUnsavedConversationOne")
        try:
            service.record_conversation_turn("user", "unsaved one memory")
            first_history = service.conversation_history()
            self.assertEqual(first_history["scope"]["kind"], "unsaved_document")
            self.assertFalse(first_history["scope"]["persistent"])
            self.assertEqual(first_history["turn_count"], 1)

            doc_two = App.newDocument("VibeCADUnsavedConversationTwo")
            App.setActiveDocument(doc_two.Name)
            second_history = service.conversation_history()
            self.assertEqual(second_history["scope"]["kind"], "unsaved_document")
            self.assertFalse(second_history["scope"]["persistent"])
            self.assertEqual(second_history["conversation"], [])
            self.assertNotIn(
                "unsaved one memory",
                json.dumps(service.context_summary()["conversation"]),
            )
        finally:
            for document in list(App.listDocuments().values()):
                App.closeDocument(document.Name)

    def test_prompt_with_conversation_marks_memory_as_document_scoped(self):
        prompt = _prompt_with_conversation(
            "Continue the bracket",
            {
                "conversation": {
                    "scope": {
                        "kind": "saved_document",
                        "document": "BracketDoc",
                        "file_path": "/tmp/bracket.FCStd",
                    },
                    "conversation": [
                        {"role": "user", "content": "Make a mounting bracket."},
                        {"role": "assistant", "content": "Created the base body."},
                    ],
                }
            },
        )

        self.assertIn("only as current document/project memory", prompt)
        self.assertIn("Conversation scope: scope=saved_document", prompt)
        self.assertIn("document=BracketDoc", prompt)
        self.assertIn("file=/tmp/bracket.FCStd", prompt)
        self.assertIn("do not treat unrelated documents", prompt)
        self.assertIn("Current user request: Continue the bracket", prompt)

    def test_loop_requirements_are_state_based_not_prompt_keyword_gates(self):
        prompts = (
            "Make me a mounting bracket with bolt holes and chamfered edges.",
            "Make me a robot with at least: base, shoulder, wrist.",
            "Paint this assembly with transparent blue material appearance.",
            "Create a TechDraw detail drawing page for this model.",
        )
        empty_context = {"document": {"object_count": 0, "objects": []}}
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(_missing_requirement_lines(prompt, empty_context, []), [])

        attempted_write = [{"tool_name": "partdesign.pad_sketch", "ok": False, "safety": "safe_write"}]
        self.assertIn(
            "first meaningful native FreeCAD geometry",
            _missing_requirement_lines("Any prompt text", empty_context, attempted_write)[0],
        )

        sketch_context = {
            "document": {"object_count": 1, "objects": [{"type": "Sketcher::SketchObject"}]},
            "sketcher": {
                "profile_status": {
                    "found": True,
                    "sketch": "Sketch",
                    "geometry_count": 4,
                    "closed_profile": True,
                    "fully_constrained": False,
                    "degrees_of_freedom": 2,
                }
            },
        }
        self.assertEqual(
            _missing_requirement_lines("No keyword dependency", sketch_context, []),
            ["- fully constrain Sketch (2 degrees of freedom) before creating dependent features"],
        )

    def test_loop_requirements_need_fresh_screenshot_after_latest_write(self):
        context = {
            "document": {
                "object_count": 2,
                "objects": [{"type": "PartDesign::Body"}, {"type": "PartDesign::Pad"}],
            },
            "view_screenshot": {
                "captured": True,
                "file_size": 1234,
                "visual_observation": {"available": True, "mostly_blank": False},
            },
        }
        write = {
            "tool_name": "partdesign.pad_sketch",
            "ok": True,
            "safety": SafetyLevel.SAFE_WRITE.value,
        }
        screenshot = {
            "tool_name": "core.capture_view_screenshot",
            "ok": True,
            "safety": SafetyLevel.VIEW.value,
        }

        stale_lines = _missing_requirement_lines(
            "Create CAD geometry",
            context,
            [screenshot, write],
        )
        self.assertIn("after the latest geometry changes", stale_lines[-1])

        fresh_lines = _missing_requirement_lines(
            "Create CAD geometry",
            context,
            [write, screenshot],
        )
        self.assertNotIn("after the latest geometry changes", "\n".join(fresh_lines))

    def test_loop_requirements_do_not_parse_prompt_for_scenario_gates(self):
        context = {
            "document": {
                "object_count": 3,
                "objects": [
                    {"type": "PartDesign::Body"},
                    {"type": "PartDesign::Pad"},
                    {"type": "Sketcher::SketchObject"},
                ],
            },
            "partdesign": {
                "bodies": [
                    {
                        "features": [
                            {"type": "Sketcher::SketchObject"},
                            {"type": "PartDesign::Pad"},
                        ]
                    },
                ]
            },
            "assembly": {"assembly_count": 0, "assemblies": []},
        }
        lines = _missing_requirement_lines(
            "Create a native assembly with at least four surviving native PartDesign features.",
            context,
            [],
        )
        self.assertFalse(any("native PartDesign feature depth" in line for line in lines), lines)
        self.assertFalse(any("native Assembly object" in line for line in lines), lines)

    def test_loop_requirements_require_assembly_for_multi_body_state(self):
        context = {
            "document": {
                "object_count": 4,
                "objects": [
                    {"type": "PartDesign::Body"},
                    {"type": "PartDesign::Pad"},
                    {"type": "PartDesign::Body"},
                    {"type": "PartDesign::Pad"},
                ],
            },
            "partdesign": {
                "body_count": 2,
                "bodies": [
                    {"features": [{"type": "PartDesign::Pad"}]},
                    {"features": [{"type": "PartDesign::Pad"}]},
                ],
            },
            "assembly": {"assembly_count": 0, "assemblies": []},
        }
        for prompt in (
            "Continue this model.",
            "Create a native assembly with at least four surviving native PartDesign features.",
        ):
            with self.subTest(prompt=prompt):
                lines = _missing_requirement_lines(prompt, context, [])
                self.assertTrue(any("multi-body component geometry" in line for line in lines), lines)
                self.assertFalse(any("native PartDesign feature depth" in line for line in lines), lines)

        context["assembly"] = {"assembly_count": 1, "assemblies": [{"components": 1}]}
        lines = _missing_requirement_lines("Continue this model.", context, [])
        self.assertTrue(any("fewer components than generated PartDesign bodies" in line for line in lines), lines)

        context["assembly"] = {"assembly_count": 1, "assemblies": [{"components": 2}]}
        lines = _missing_requirement_lines("Continue this model.", context, [])
        self.assertFalse(any("Assembly" in line or "component bodies" in line for line in lines), lines)

    def test_provider_safe_tool_schemas_expose_only_command_write_tools(self):
        service = VibeCADService()
        names = {schema["name"] for schema in provider_safe_tool_schemas(service)}
        self.assertIn("core.get_active_document", names)
        self.assertIn("core.create_new_document", names)
        self.assertIn("core.open_document", names)
        self.assertIn("core.delete_object", names)
        self.assertIn("core.report_tool_shape_gap", names)
        self.assertNotIn("core.run_workbench_command", names)
        self.assertIn("core.get_tool_shape_report", names)
        self.assertIn("core.wait_for_user_gui_action", names)
        self.assertNotIn("core.propose_run_workbench_command", names)
        self.assertIn("core.capture_view_screenshot", names)
        self.assertIn("core.get_report_view_errors", names)
        self.assertNotIn("core.propose_create_part_box", names)
        self.assertNotIn("core.propose_create_workbench_object", names)
        self.assertNotIn("core.propose_set_object_label", names)
        self.assertNotIn("core.propose_set_selected_property", names)
        self.assertNotIn("core.list_pending_actions", names)
        self.assertNotIn("core.apply_action", names)
        self.assertNotIn("core.reject_action", names)
        self.assertNotIn("core.undo_last_vibecad_action", names)
        self.assertNotIn("core.clear_local_session", names)
        self.assertNotIn("core.run_workbench_command", names)

    def test_provider_tool_modules_cover_provider_safe_tools(self):
        from provider_tools import registered_tool_names

        service = VibeCADService()
        workbenches = [
            "PartWorkbench",
            "PartDesignWorkbench",
            "SketcherWorkbench",
            "DraftWorkbench",
            "AssemblyWorkbench",
            "TechDrawWorkbench",
            "MaterialWorkbench",
            "NoneWorkbench",
        ]
        missing = []
        registered = registered_tool_names()
        for workbench in workbenches:
            for schema in provider_safe_tool_schemas(service, workbench):
                if schema["name"] not in registered:
                    missing.append((workbench, schema["name"]))
        self.assertEqual(missing, [])

    def test_provider_tool_registry_contains_only_direct_model_tools(self):
        from provider_tools import registered_tool_names

        names = registered_tool_names()
        self.assertFalse([name for name in names if ".propose_" in name], names)
        self.assertNotIn("core.list_pending_actions", names)
        self.assertNotIn("core.apply_action", names)
        self.assertNotIn("core.reject_action", names)
        self.assertNotIn("core.undo_last_vibecad_action", names)
        self.assertNotIn("core.clear_local_session", names)

    def test_provider_safe_tool_schemas_are_workbench_scoped(self):
        service = VibeCADService()
        part_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "PartWorkbench")
        }
        sketcher_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
        }
        self.assertIn("part.get_objects", part_names)
        self.assertIn("part.create_primitive", part_names)
        self.assertIn("part.set_placement", part_names)
        self.assertIn("part.set_primitive_dimensions", part_names)
        self.assertIn("part.cut_cylindrical_hole", part_names)
        self.assertIn("part.apply_fillet", part_names)
        self.assertIn("part.apply_chamfer", part_names)
        self.assertIn("part.apply_thickness", part_names)
        self.assertNotIn("draft.create_array", part_names)
        self.assertNotIn("core.run_workbench_command", part_names)
        self.assertNotIn("core.propose_run_workbench_command", part_names)
        self.assertNotIn("core.propose_create_part_box", part_names)
        self.assertNotIn("part.propose_create_primitive", part_names)
        self.assertNotIn("core.propose_create_part_box", sketcher_names)
        self.assertNotIn("part.propose_create_primitive", sketcher_names)
        self.assertNotIn("core.propose_create_workbench_object", sketcher_names)
        self.assertIn("core.report_tool_shape_gap", sketcher_names)
        self.assertIn("sketcher.get_sketch", sketcher_names)
        self.assertIn("sketcher.create_sketch", sketcher_names)
        self.assertIn("sketcher.open_sketch", sketcher_names)
        self.assertIn("sketcher.close_sketch", sketcher_names)
        self.assertIn("sketcher.get_solver_status", sketcher_names)
        self.assertIn("sketcher.validate_profile", sketcher_names)
        self.assertIn("sketcher.validate_profile_deep", sketcher_names)
        self.assertIn("sketcher.diagnose_constraints", sketcher_names)
        self.assertIn("sketcher.list_geometry", sketcher_names)
        self.assertIn("sketcher.list_constraints", sketcher_names)
        self.assertIn("sketcher.resolve_geometry", sketcher_names)
        self.assertIn("sketcher.set_geometry_name", sketcher_names)
        self.assertIn("sketcher.list_reference_geometry", sketcher_names)
        self.assertIn("sketcher.list_external_geometry", sketcher_names)
        self.assertIn("sketcher.add_line", sketcher_names)
        self.assertIn("sketcher.add_point", sketcher_names)
        self.assertIn("sketcher.add_polyline", sketcher_names)
        self.assertIn("sketcher.add_circle", sketcher_names)
        self.assertIn("sketcher.add_arc", sketcher_names)
        self.assertIn("sketcher.add_ellipse", sketcher_names)
        self.assertIn("sketcher.add_bspline", sketcher_names)
        self.assertIn("sketcher.add_slot", sketcher_names)
        self.assertIn("sketcher.add_constraint", sketcher_names)
        self.assertIn("sketcher.constrain_coincident", sketcher_names)
        self.assertIn("sketcher.constrain_horizontal", sketcher_names)
        self.assertIn("sketcher.constrain_vertical", sketcher_names)
        self.assertIn("sketcher.constrain_parallel", sketcher_names)
        self.assertIn("sketcher.constrain_perpendicular", sketcher_names)
        self.assertIn("sketcher.constrain_tangent", sketcher_names)
        self.assertIn("sketcher.constrain_equal", sketcher_names)
        self.assertIn("sketcher.constrain_distance", sketcher_names)
        self.assertIn("sketcher.constrain_distance_points", sketcher_names)
        self.assertIn("sketcher.constrain_distance_x", sketcher_names)
        self.assertIn("sketcher.constrain_distance_y", sketcher_names)
        self.assertIn("sketcher.constrain_angle_between", sketcher_names)
        self.assertIn("sketcher.constrain_lock_point", sketcher_names)
        self.assertIn("sketcher.constrain_block_geometry", sketcher_names)
        self.assertIn("sketcher.constrain_radius", sketcher_names)
        self.assertIn("sketcher.constrain_diameter", sketcher_names)
        self.assertIn("sketcher.constrain_point_on_object", sketcher_names)
        self.assertIn("sketcher.constrain_point_on_reference", sketcher_names)
        self.assertIn("sketcher.constrain_symmetric", sketcher_names)
        self.assertIn("sketcher.get_constraint_by_name", sketcher_names)
        self.assertIn("sketcher.set_constraint_name", sketcher_names)
        self.assertIn("sketcher.set_constraint_value", sketcher_names)
        self.assertIn("sketcher.set_constraint_value_by_name", sketcher_names)
        self.assertIn("sketcher.set_constraint_driving", sketcher_names)
        self.assertIn("sketcher.set_constraint_expression", sketcher_names)
        self.assertIn("sketcher.move_point", sketcher_names)
        self.assertIn("sketcher.transform_geometry", sketcher_names)
        self.assertIn("sketcher.copy_geometry", sketcher_names)
        self.assertIn("sketcher.rectangular_array", sketcher_names)
        self.assertIn("sketcher.mirror_geometry", sketcher_names)
        self.assertIn("sketcher.offset_geometry", sketcher_names)
        self.assertIn("sketcher.trim_geometry", sketcher_names)
        self.assertIn("sketcher.extend_geometry", sketcher_names)
        self.assertIn("sketcher.split_geometry", sketcher_names)
        self.assertIn("sketcher.fillet_corner", sketcher_names)
        self.assertIn("sketcher.add_external_geometry", sketcher_names)
        self.assertIn("sketcher.remove_external_geometry", sketcher_names)
        self.assertIn("sketcher.delete_geometry", sketcher_names)
        self.assertIn("sketcher.delete_constraint", sketcher_names)
        self.assertIn("sketcher.delete_all_geometry", sketcher_names)
        self.assertIn("sketcher.delete_all_constraints", sketcher_names)
        self.assertIn("sketcher.set_construction", sketcher_names)
        self.assertNotIn("sketcher.propose_add_line", sketcher_names)
        self.assertNotIn("sketcher.propose_add_line", part_names)
        spreadsheet_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "SpreadsheetWorkbench")
        }
        self.assertIn("spreadsheet.get_sheet", spreadsheet_names)
        self.assertNotIn("spreadsheet.propose_set_cell", spreadsheet_names)
        self.assertNotIn("spreadsheet.propose_set_cell", part_names)
        draft_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "DraftWorkbench")
        }
        self.assertIn("draft.get_objects", draft_names)
        self.assertIn("draft.create_array", draft_names)
        self.assertNotIn("draft.propose_create_line", draft_names)
        self.assertNotIn("draft.propose_create_line", part_names)
        partdesign_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "PartDesignWorkbench")
        }
        self.assertIn("partdesign.get_bodies", partdesign_names)
        self.assertIn("partdesign.create_body", partdesign_names)
        self.assertIn("partdesign.create_sketch", partdesign_names)
        self.assertIn("partdesign.pad_sketch", partdesign_names)
        self.assertIn("partdesign.pocket_sketch", partdesign_names)
        self.assertIn("partdesign.hole_from_sketch", partdesign_names)
        self.assertIn("partdesign.revolve_sketch", partdesign_names)
        self.assertIn("partdesign.loft_profiles", partdesign_names)
        self.assertIn("partdesign.sweep_profile", partdesign_names)
        self.assertIn("partdesign.linear_pattern", partdesign_names)
        self.assertIn("partdesign.polar_pattern", partdesign_names)
        self.assertIn("partdesign.mirror_feature", partdesign_names)
        self.assertIn("partdesign.fillet_feature", partdesign_names)
        self.assertIn("partdesign.chamfer_feature", partdesign_names)
        self.assertIn("partdesign.thickness_feature", partdesign_names)
        self.assertIn("partdesign.set_feature_dimensions", partdesign_names)
        self.assertIn("sketcher.add_line", partdesign_names)
        self.assertIn("sketcher.add_circle", partdesign_names)
        self.assertIn("sketcher.add_arc", partdesign_names)
        self.assertIn("sketcher.add_slot", partdesign_names)
        self.assertIn("sketcher.add_constraint", partdesign_names)
        self.assertIn("sketcher.draw_rectangle", partdesign_names)
        self.assertIn("sketcher.validate_profile_deep", partdesign_names)
        self.assertIn("sketcher.diagnose_constraints", partdesign_names)
        self.assertIn("sketcher.transform_geometry", partdesign_names)
        self.assertIn("sketcher.copy_geometry", partdesign_names)
        self.assertIn("sketcher.rectangular_array", partdesign_names)
        self.assertIn("sketcher.mirror_geometry", partdesign_names)
        self.assertIn("sketcher.offset_geometry", partdesign_names)
        self.assertIn("sketcher.delete_all_geometry", partdesign_names)
        self.assertIn("sketcher.delete_all_constraints", partdesign_names)
        self.assertNotIn("sketcher.create_sketch", partdesign_names)
        self.assertNotIn("core.run_workbench_command", partdesign_names)
        self.assertNotIn("part.create_primitive", partdesign_names)
        self.assertNotIn("part.set_placement", partdesign_names)
        self.assertNotIn("part.set_primitive_dimensions", partdesign_names)
        self.assertNotIn("part.cut_cylindrical_hole", partdesign_names)
        self.assertNotIn("part.get_objects", partdesign_names)
        self.assertNotIn("draft.create_array", partdesign_names)
        self.assertNotIn("draft.get_objects", partdesign_names)
        self.assertNotIn("assembly.create_assembly", partdesign_names)
        self.assertNotIn("assembly.add_component", partdesign_names)
        self.assertNotIn("assembly.get_assemblies", partdesign_names)
        self.assertNotIn("techdraw.create_page", partdesign_names)
        self.assertNotIn("techdraw.add_view", partdesign_names)
        self.assertNotIn("techdraw.get_pages", partdesign_names)
        self.assertNotIn("material.apply_appearance", partdesign_names)
        self.assertNotIn("material.get_objects", partdesign_names)

        self.assertLess(len(partdesign_names), 100)
        self.assertNotIn("partdesign.propose_create_body", partdesign_names)
        self.assertNotIn("partdesign.propose_add_box", partdesign_names)
        self.assertNotIn("partdesign.propose_add_box", part_names)
        self.assertNotIn("partdesign.create_sketch", part_names)
        techdraw_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "TechDrawWorkbench")
        }
        self.assertIn("techdraw.get_pages", techdraw_names)
        self.assertIn("techdraw.create_page", techdraw_names)
        self.assertIn("techdraw.add_view", techdraw_names)
        self.assertNotIn("techdraw.propose_create_page", techdraw_names)
        self.assertNotIn("techdraw.propose_create_page", part_names)

        fem_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "FemWorkbench")
        }
        self.assertIn("fem.get_analyses", fem_names)
        self.assertNotIn("fem.propose_create_analysis", fem_names)
        self.assertNotIn("fem.propose_create_analysis", part_names)
        cam_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "CAMWorkbench")
        }
        self.assertIn("cam.get_jobs", cam_names)
        self.assertNotIn("cam.propose_create_job", cam_names)
        self.assertNotIn("cam.propose_create_job", part_names)
        bim_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "BIMWorkbench")
        }
        self.assertIn("bim.get_objects", bim_names)
        self.assertNotIn("bim.propose_create_container", bim_names)
        self.assertNotIn("bim.propose_create_container", part_names)
        assembly_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "AssemblyWorkbench")
        }
        self.assertIn("assembly.get_assemblies", assembly_names)
        self.assertIn("assembly.create_assembly", assembly_names)
        self.assertIn("assembly.add_component", assembly_names)
        self.assertIn("assembly.set_component_placement", assembly_names)
        self.assertNotIn("assembly.propose_create_assembly", assembly_names)
        self.assertNotIn("assembly.propose_create_assembly", part_names)
        inspection_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "InspectionWorkbench")
        }
        self.assertIn("inspection.get_objects", inspection_names)
        self.assertNotIn("inspection.propose_create_inspection", inspection_names)
        self.assertNotIn("inspection.propose_create_inspection", part_names)
        openscad_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "OpenSCADWorkbench")
        }
        self.assertIn("openscad.get_objects", openscad_names)
        self.assertNotIn("openscad.propose_import_csg", openscad_names)
        self.assertNotIn("openscad.propose_import_csg", part_names)
        surface_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "SurfaceWorkbench")
        }
        self.assertIn("surface.get_objects", surface_names)
        self.assertNotIn("surface.propose_create_feature", surface_names)
        self.assertNotIn("surface.propose_create_feature", part_names)
        reen_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "ReverseEngineeringWorkbench")
        }
        self.assertIn("reverseengineering.get_objects", reen_names)
        self.assertNotIn("reverseengineering.propose_approximate_curve", reen_names)
        self.assertNotIn("reverseengineering.propose_approximate_curve", part_names)
        robot_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "RobotWorkbench")
        }
        self.assertIn("robot.get_objects", robot_names)
        self.assertNotIn("robot.propose_add_waypoint", robot_names)
        self.assertNotIn("robot.propose_add_waypoint", part_names)
        meshpart_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "MeshPartWorkbench")
        }
        self.assertIn("meshpart.get_objects", meshpart_names)
        self.assertNotIn("meshpart.propose_tessellate_shape", meshpart_names)
        self.assertNotIn("meshpart.propose_tessellate_shape", part_names)
        mesh_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "MeshWorkbench")
        }
        self.assertIn("mesh.get_objects", mesh_names)
        self.assertNotIn("mesh.propose_create_primitive", mesh_names)
        self.assertNotIn("mesh.propose_create_primitive", part_names)
        points_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "PointsWorkbench")
        }
        self.assertIn("points.get_objects", points_names)
        self.assertNotIn("points.propose_create_cloud", points_names)
        self.assertNotIn("points.propose_create_cloud", part_names)
        material_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "MaterialWorkbench")
        }
        self.assertIn("material.get_objects", material_names)
        self.assertIn("material.apply_appearance", material_names)
        self.assertNotIn("material.propose_apply_appearance", material_names)
        self.assertNotIn("material.propose_apply_appearance", part_names)
        test_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "TestWorkbench")
        }
        self.assertIn("core.list_active_workbench_commands", test_names)
        self.assertNotIn("core.run_workbench_command", test_names)
        self.assertNotIn("core.propose_run_workbench_command", test_names)
        self.assertNotIn("part.propose_create_primitive", test_names)
        none_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "NoneWorkbench")
        }
        self.assertIn("core.get_active_document", none_names)
        self.assertNotIn("core.run_workbench_command", none_names)
        self.assertNotIn("core.propose_create_workbench_object", none_names)
        self.assertNotIn("part.propose_create_primitive", none_names)

    def test_provider_tool_scope_reduces_sketcher_no_sketch_surface(self):
        service = VibeCADService()
        full_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
        }
        scope = provider_tool_scope_for_context(service, "SketcherWorkbench")
        scoped_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(
                service,
                "SketcherWorkbench",
                tool_names=scope.tool_names,
            )
        }

        self.assertIsInstance(scope, ProviderToolScope)
        self.assertEqual(scope.phase, "sketcher_no_active_sketch")
        self.assertLess(len(scoped_names), len(full_names))
        self.assertIn("core.get_active_document", scoped_names)
        self.assertIn("sketcher.create_sketch", scoped_names)
        self.assertIn("sketcher.get_sketch", scoped_names)
        self.assertNotIn("sketcher.add_line", scoped_names)
        self.assertNotIn("sketcher.constrain_distance", scoped_names)
        self.assertNotIn("sketcher.offset_geometry", scoped_names)

    def test_provider_tool_scope_progresses_sketcher_by_state_not_prompt(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketcherToolScopeTest")
        try:
            service = VibeCADService()
            full_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
            }
            sketch_result = service.registry.call(
                "sketcher.create_sketch",
                label="Scoped Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(sketch_result["ok"], sketch_result)

            empty_scope = provider_tool_scope_for_context(service, "SketcherWorkbench")
            empty_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(
                    service,
                    "SketcherWorkbench",
                    tool_names=empty_scope.tool_names,
                )
            }
            self.assertEqual(empty_scope.phase, "sketcher_geometry_authoring")
            self.assertIn("sketcher.add_line", empty_names)
            self.assertIn("sketcher.draw_rectangle", empty_names)
            self.assertIn("sketcher.close_sketch", empty_names)
            self.assertNotIn("sketcher.constrain_distance", empty_names)

            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            line = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(line["ok"], line)

            constraint_scope = provider_tool_scope_for_context(service, "SketcherWorkbench")
            constraint_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(
                    service,
                    "SketcherWorkbench",
                    tool_names=constraint_scope.tool_names,
                )
            }
            self.assertEqual(constraint_scope.phase, "sketcher_profile_authoring")
            self.assertIn("sketcher.constrain_coincident", constraint_names)
            self.assertIn("sketcher.move_point", constraint_names)
            self.assertIn("sketcher.trim_geometry", constraint_names)
            self.assertIn("sketcher.draw_rectangle", constraint_names)
            self.assertNotIn("sketcher.constrain_distance", constraint_names)
            self.assertNotIn("sketcher.offset_geometry", constraint_names)
            self.assertNotIn("sketcher.mirror_geometry", constraint_names)
            self.assertLess(len(constraint_names), len(full_names))
        finally:
            App.closeDocument(doc.Name)

    def test_provider_tool_scope_reduces_partdesign_setup_surface(self):
        service = VibeCADService()
        full_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "PartDesignWorkbench")
        }
        scope = provider_tool_scope_for_context(service, "PartDesignWorkbench")
        scoped_names = {
            schema["name"]
            for schema in provider_safe_tool_schemas(
                service,
                "PartDesignWorkbench",
                tool_names=scope.tool_names,
            )
        }

        self.assertEqual(scope.phase, "partdesign_setup")
        self.assertLess(len(scoped_names), len(full_names))
        self.assertIn("partdesign.create_body", scoped_names)
        self.assertIn("partdesign.create_sketch", scoped_names)
        self.assertNotIn("sketcher.add_line", scoped_names)
        self.assertNotIn("partdesign.pad_sketch", scoped_names)

    def test_provider_tool_scope_progresses_partdesign_by_model_state(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignToolScopeTest")
        try:
            service = VibeCADService()
            body = service.registry.call("partdesign.create_body", label="Scoped Body")
            self.assertTrue(body["ok"], body)
            sketch_result = service.registry.call(
                "partdesign.create_sketch",
                body_name=body["active_body"],
                label="Scoped Rectangle",
                plane="XY_Plane",
            )
            self.assertTrue(sketch_result["ok"], sketch_result)
            rectangle = service.registry.call(
                "sketcher.draw_rectangle",
                sketch_name=sketch_result["active_sketch"],
                width=20,
                height=10,
                center_x=0,
                center_y=0,
            )
            self.assertTrue(rectangle["ok"], rectangle)

            feature_scope = provider_tool_scope_for_context(service, "PartDesignWorkbench")
            feature_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(
                    service,
                    "PartDesignWorkbench",
                    tool_names=feature_scope.tool_names,
                )
            }
            self.assertEqual(feature_scope.phase, "partdesign_base_feature_creation")
            self.assertIn("sketcher.close_sketch", feature_names)
            self.assertIn("partdesign.pad_sketch", feature_names)
            self.assertIn("partdesign.pocket_sketch", feature_names)
            self.assertIn("partdesign.revolve_sketch", feature_names)
            self.assertNotIn("sketcher.add_line", feature_names)
            self.assertNotIn("partdesign.fillet_feature", feature_names)

            pad = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=sketch_result["active_sketch"],
                label="Scoped Pad",
                length=5,
            )
            self.assertTrue(pad["ok"], pad)

            revision_scope = provider_tool_scope_for_context(service, "PartDesignWorkbench")
            revision_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(
                    service,
                    "PartDesignWorkbench",
                    tool_names=revision_scope.tool_names,
                )
            }
            self.assertEqual(revision_scope.phase, "partdesign_feature_and_revision")
            self.assertIn("partdesign.fillet_feature", revision_names)
            self.assertIn("partdesign.chamfer_feature", revision_names)
            self.assertIn("partdesign.linear_pattern", revision_names)
            self.assertIn("partdesign.create_sketch", revision_names)
            self.assertNotIn("sketcher.constrain_distance", revision_names)
            self.assertNotIn("sketcher.offset_geometry", revision_names)
        finally:
            App.closeDocument(doc.Name)

    def test_autonomous_loop_refreshes_scoped_tool_surface_between_turns(self):
        import FreeCAD as App

        class ScopeProbeProvider(BaseProvider):
            def __init__(self):
                self.scopes = []
                self.tool_names = []

            def run(self, _prompt, context, tool_runner=None):
                scope = dict(context.get("provider_tool_scope") or {})
                names = [
                    schema.get("name")
                    for schema in context.get("provider_tool_schemas", [])
                    if isinstance(schema, dict)
                ]
                self.scopes.append(scope)
                self.tool_names.append(names)
                if len(self.scopes) == 1:
                    self.assert_tool(tool_runner)
                    tool_runner("partdesign.create_body", '{"label": "Scoped Body"}')
                    return ProviderResult("Progress checkpoint so the tool context can refresh.")
                return ProviderResult("Scoped tool surface refreshed; stopping.")

            @staticmethod
            def assert_tool(tool_runner):
                if tool_runner is None:
                    raise AssertionError("tool_runner is required")

        doc = App.newDocument("VibeCADScopedTurnRefreshTest")
        try:
            service = VibeCADService()
            service.active_workbench_name = lambda: "PartDesignWorkbench"  # type: ignore[method-assign]
            provider = ScopeProbeProvider()
            response = run_prompt(
                "Create a PartDesign part in small verified steps.",
                service=service,
                provider=provider,
                enforce_small_steps=True,
            )

            self.assertEqual(response.provider, "ScopeProbeProvider")
            self.assertGreaterEqual(len(provider.scopes), 2)
            self.assertEqual(provider.scopes[0]["phase"], "partdesign_setup")
            self.assertEqual(provider.scopes[1]["phase"], "partdesign_sketch_authoring")
            self.assertIn("partdesign.create_body", provider.tool_names[0])
            self.assertNotIn("sketcher.add_line", provider.tool_names[0])
            self.assertIn("sketcher.add_line", provider.tool_names[1])
            self.assertIn("partdesign.create_sketch", provider.tool_names[1])
            self.assertTrue(
                any(
                    getattr(obj, "TypeId", "") == "PartDesign::Body"
                    and getattr(obj, "Label", "") == "Scoped Body"
                    for obj in doc.Objects
                )
            )
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_create_sketch_forces_tool_surface_refresh_checkpoint(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCreateSketchRefreshCheckpointTest")
        try:
            service = VibeCADService()
            service.active_workbench_name = lambda: "PartDesignWorkbench"  # type: ignore[method-assign]
            body = service.registry.call("partdesign.create_body", label="Checkpoint Body")
            self.assertTrue(body["ok"], body)
            trace = []
            runner = make_provider_tool_runner(
                service,
                "PartDesignWorkbench",
                tool_trace=trace,
                turn_state={"turn": 1, "mutating_tool_calls": 0},
            )

            result = runner(
                "partdesign.create_sketch",
                '{"body_name": "Checkpoint Body", "label": "Component Sketch", "plane": "XY_Plane"}',
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result.get("checkpoint"), "tool_surface_refresh")
            self.assertEqual(
                result["required_next_action"]["next_turn_workbench"],
                "SketcherWorkbench",
            )
            self.assertIn(
                "sketcher.draw_rectangle",
                result["required_next_action"]["expected_tools"],
            )

            blocked = runner(
                "sketcher.draw_rectangle",
                '{"sketch_name": "Component Sketch", "width": 10, "height": 10}',
            )
            self.assertTrue(blocked["ok"], blocked)
            self.assertEqual(blocked.get("status"), "deferred_checkpoint")
            self.assertFalse(blocked.get("executed"))
            self.assertEqual(blocked.get("checkpoint"), "tool_surface_refresh")
        finally:
            App.closeDocument(doc.Name)

    def test_provider_workbench_stays_partdesign_while_editing_body_sketch(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignEffectiveWorkbenchTest")
        try:
            service = VibeCADService()
            service.registry.call("partdesign.create_body", label="Body")
            service.registry.call("partdesign.create_sketch", label="Sketch")

            effective = _effective_provider_workbench(service, "SketcherWorkbench")
            self.assertEqual(effective, "PartDesignWorkbench")

            names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, effective)
            }
            self.assertIn("partdesign.create_sketch", names)
            self.assertIn("sketcher.draw_rectangle", names)
            self.assertNotIn("sketcher.create_sketch", names)
        finally:
            App.closeDocument(doc.Name)

    def test_provider_safe_sketcher_context_exposes_partdesign_feature_tools_after_sketch_exists(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketcherPartDesignBridgeTest")
        try:
            service = VibeCADService()
            before_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
            }
            self.assertNotIn("partdesign.pocket_sketch", before_names)

            sketch_result = service.registry.call(
                "sketcher.create_sketch",
                label="Bridge Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(sketch_result["ok"], sketch_result)
            after_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
            }
            self.assertIn("partdesign.pad_sketch", after_names)
            self.assertIn("partdesign.pocket_sketch", after_names)
            self.assertIn("partdesign.revolve_sketch", after_names)
        finally:
            App.closeDocument(doc.Name)

    def test_part_primitive_provider_tools_are_opt_in(self):
        old_settings = load_settings()
        try:
            save_settings(
                VibeCADSettings(
                    use_online_provider=old_settings.use_online_provider,
                    model=old_settings.model,
                    dotenv_path=old_settings.dotenv_path,
                    disabled_workbenches=old_settings.disabled_workbenches,
                    reasoning_effort=old_settings.reasoning_effort,
                    allow_primitive_provider_tools=False,
                )
            )
            service = VibeCADService()
            names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, "PartWorkbench")
            }
            self.assertIn("part.get_objects", names)
            self.assertNotIn("part.create_primitive", names)
            self.assertNotIn("part.set_placement", names)
            self.assertNotIn("part.cut_cylindrical_hole", names)
            blocked = make_provider_tool_runner(service, "PartWorkbench")(
                "part.create_primitive",
                '{"primitive_type": "box", "label": "Blocked"}',
            )
            self.assertFalse(blocked["ok"])
            self.assertIn("Part primitive write tools are disabled", blocked["error"])

            save_settings(
                VibeCADSettings(
                    use_online_provider=old_settings.use_online_provider,
                    model=old_settings.model,
                    dotenv_path=old_settings.dotenv_path,
                    disabled_workbenches=old_settings.disabled_workbenches,
                    reasoning_effort=old_settings.reasoning_effort,
                    allow_primitive_provider_tools=True,
                )
            )
            allowed_names = {
                schema["name"]
                for schema in provider_safe_tool_schemas(service, "PartWorkbench")
            }
            self.assertIn("part.create_primitive", allowed_names)
            self.assertIn("part.set_placement", allowed_names)
            self.assertIn("part.cut_cylindrical_hole", allowed_names)
        finally:
            save_settings(old_settings)

    def test_provider_tool_runner_blocks_direct_write_tools(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service)
        blocked = runner("core.apply_action", '{"action_id": "action-1"}')
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["safety"], "write")
        self.assertEqual(len(service.pending_actions()["pending"]), 0)

    def test_provider_tool_runner_blocks_out_of_scope_workbench_tools(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service, "SketcherWorkbench")
        blocked = runner("part.create_primitive", '{"primitive_type": "box", "label": "Wrong"}')
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["tool_workbench"], "PartWorkbench")
        self.assertIn("Tool is not available", blocked["error"])

    def test_provider_tool_runner_rejects_part_primitives_in_partdesign(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service, "PartDesignWorkbench")
        blocked = runner(
            "part.create_primitive",
            '{"primitive_type": "box", "label": "Wrong primitive block"}',
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("Tool is not available for the active workbench", blocked["error"])
        self.assertEqual(blocked["active_workbench"], "PartDesignWorkbench")
        self.assertEqual(blocked["tool_workbench"], "PartWorkbench")

    def test_provider_tool_runner_requires_explicit_workbench_switch(self):
        if not _gui_workbench_api_available():
            self.skipTest("FreeCAD GUI workbench API unavailable")
        import FreeCAD as App

        service = VibeCADService()
        runner = make_provider_tool_runner(service, "PartWorkbench")
        blocked = runner(
            "partdesign.create_sketch",
            '{"label": "Auto Switch Sketch", "plane": "XY_Plane"}',
        )
        doc = App.ActiveDocument
        try:
            self.assertTrue(blocked["ok"], blocked)
            result = blocked["result"]
            self.assertEqual(result["transaction"]["result"]["sketch_label"], "Auto Switch Sketch")
            self.assertIsNotNone(result["active_sketch"])
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)

    def test_provider_tool_runner_does_not_checkpoint_same_workbench_activation(self):
        if not _gui_workbench_api_available():
            self.skipTest("FreeCAD GUI workbench API unavailable")
        service = VibeCADService()
        service.activate_workbench("PartDesignWorkbench")
        turn_state = {"turn": 1, "mutating_tool_calls": 0, "checkpoint_reached": False}
        runner = make_provider_tool_runner(
            service,
            "PartDesignWorkbench",
            turn_state=turn_state,
        )
        result = runner("core.activate_workbench", '{"name": "PartDesignWorkbench"}')

        self.assertTrue(result["ok"], result)
        self.assertNotEqual(result.get("checkpoint"), "workbench_switch")
        self.assertFalse(turn_state.get("workbench_switch_reached", False))

    def test_autonomous_loop_continues_after_workbench_switch_checkpoint(self):
        trace = [
            {
                "tool_name": "core.activate_workbench",
                "ok": True,
                "result": {"ok": True, "checkpoint": "workbench_switch"},
            }
        ]
        self.assertTrue(_tool_batch_checkpoint_reached(trace))
        service = VibeCADService()
        self.assertTrue(
            _should_continue_autonomously(
                "Design a usable quadcopter drone concept.",
                "Checkpoint after required workbench switch.",
                service,
                trace,
                turn_index=1,
            )
        )

    def test_provider_tool_runner_uses_actual_active_workbench_before_each_call(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADLiveWorkbenchTrackingTest")
        try:
            service = VibeCADService()
            service.active_workbench_name = lambda: "SketcherWorkbench"  # type: ignore[method-assign]
            runner = make_provider_tool_runner(service, "PartDesignWorkbench")
            result = runner(
                "sketcher.create_sketch",
                '{"label": "Actual Workbench Sketch", "support_type": "origin_plane", "plane": "XY_Plane"}',
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                result["result"]["transaction"]["result"]["active_workbench"],
                "SketcherWorkbench",
            )
            self.assertTrue(
                any(
                    getattr(obj, "TypeId", "") == "Sketcher::SketchObject"
                    and getattr(obj, "Label", "") == "Actual Workbench Sketch"
                    for obj in doc.Objects
                )
            )
        finally:
            App.closeDocument(doc.Name)

    def test_provider_tool_runner_reports_small_step_checkpoint_after_completed_mutation(self):
        import FreeCAD as App

        service = VibeCADService()
        turn_state = {
            "turn": 1,
            "mutating_tool_calls": MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN - 1,
            "checkpoint_reached": False,
        }
        runner = make_provider_tool_runner(
            service,
            "PartDesignWorkbench",
            turn_state=turn_state,
        )
        result = runner(
            "partdesign.create_sketch",
            '{"label": "Checkpoint Sketch", "plane": "XY_Plane"}',
        )
        doc = App.ActiveDocument
        try:
            self.assertTrue(result["ok"], result)
            self.assertEqual(result.get("checkpoint"), "small_step")
            self.assertTrue(turn_state.get("checkpoint_reached"))
            self.assertEqual(
                result.get("mutating_tool_calls"),
                MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN,
            )
            self.assertEqual(
                result.get("required_next_action", {}).get("finish_current_turn"),
                True,
            )
            self.assertTrue(
                any(
                    getattr(obj, "TypeId", "") == "Sketcher::SketchObject"
                    and getattr(obj, "Label", "") == "Checkpoint Sketch"
                    for obj in (doc.Objects if doc else [])
                )
            )
        finally:
            if doc is not None:
                App.closeDocument(doc.Name)

    def test_small_step_checkpoint_limit_is_configurable(self):
        old_value = os.environ.get(MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN_ENV)
        try:
            os.environ[MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN_ENV] = "3"
            self.assertEqual(_max_mutating_tool_calls_per_provider_turn(), 3)
            state = _provider_loop_state(
                "make a bracket",
                {"document": {"object_count": 1}, "workbench": "PartDesignWorkbench"},
                [],
                turn=1,
                visual_feedback_consumed=False,
            )
            self.assertEqual(state["max_mutating_tool_calls_per_turn"], 3)
        finally:
            if old_value is None:
                os.environ.pop(MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN_ENV, None)
            else:
                os.environ[MAX_MUTATING_TOOL_CALLS_PER_PROVIDER_TURN_ENV] = old_value

    def test_autonomous_loop_continues_when_provider_reports_checkpoint(self):
        service = VibeCADService()
        self.assertTrue(
            _should_continue_autonomously(
                "Design a usable bearing carrier bracket and capture the viewport.",
                "Progress checkpoint: VibeCAD requested a checkpoint before further edits.",
                service,
                [],
                0,
                visual_feedback_consumed=True,
            )
        )

    def test_autonomous_loop_continues_when_provider_admits_ineffective_geometry(self):
        self.assertTrue(
            _assistant_stopped_without_finishing(
                "Current status: the attempted pockets were created as native "
                "PartDesign Pocket features, but repeated verification showed "
                "Body volume/faces remained unchanged, so the cutouts were not "
                "actually cutting the web. Next step after refresh: recreate "
                "the cutouts and verify volume change."
            )
        )

    def test_autonomous_loop_continues_when_verified_requirements_remain(self):
        class FakeService:
            def document_summary(self):
                return {"object_count": 4}

            def context_summary(self):
                return {
                    "document": {
                        "object_count": 4,
                        "objects": [
                            {"type": "PartDesign::Body"},
                            {"type": "PartDesign::Body"},
                            {"type": "PartDesign::Pad"},
                            {"type": "PartDesign::Pad"},
                        ],
                    },
                    "assembly": {"assembly_count": 0, "assemblies": []},
                }

            def provider_context_summary(self):
                return self.context_summary()

        self.assertTrue(
            _should_continue_autonomously(
                "Design a usable multi-part fixture assembly with native assembly structure.",
                "Created a base plate and fixed jaw.",
                FakeService(),
                [],
                0,
            )
        )

    def test_provider_tool_runner_create_document_accepts_name_argument(self):
        import FreeCAD as App

        service = VibeCADService()
        runner = make_provider_tool_runner(service)
        result = runner("core.create_new_document", '{"name": "VibeCADNamedDocument"}')
        try:
            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(App.getDocument("VibeCADNamedDocument"))
        finally:
            doc = App.getDocument("VibeCADNamedDocument")
            if doc is not None:
                App.closeDocument(doc.Name)

    def test_disabled_tool_pack_blocks_provider_surface_and_runner(self):
        old_settings = load_settings()
        try:
            save_settings(
                VibeCADSettings(disabled_workbenches=("PartWorkbench",))
            )
            service = VibeCADService()
            schemas = provider_safe_tool_schemas(service, "PartWorkbench")
            names = {schema["name"] for schema in schemas}
            self.assertIn("core.get_active_document", names)
            self.assertNotIn("core.propose_create_part_box", names)
            self.assertNotIn("part.get_objects", names)
            self.assertNotIn("part.propose_create_primitive", names)
            self.assertNotIn("core.propose_create_workbench_object", names)

            surface = service.provider_tool_surface("PartWorkbench")
            self.assertFalse(surface["tool_pack_enabled"])
            surface_names = {tool["name"] for tool in surface["tools"]}
            self.assertNotIn("part.get_objects", surface_names)
            self.assertFalse(service.is_provider_tool_available("part.get_objects", "PartWorkbench"))

            runner = make_provider_tool_runner(service, "PartWorkbench")
            blocked = runner("part.get_objects", "{}")
            self.assertFalse(blocked["ok"])
            self.assertIn("Tool pack is disabled", blocked["error"])
        finally:
            save_settings(old_settings)

    def test_provider_tool_surface_reports_scoped_tools(self):
        service = VibeCADService()
        surface = service.provider_tool_surface("PartWorkbench")
        names = {tool["name"] for tool in surface["tools"]}
        self.assertEqual(surface["active_workbench"], "PartWorkbench")
        self.assertTrue(surface["tool_pack_enabled"])
        self.assertNotIn("core.run_workbench_command", names)
        self.assertNotIn("core.propose_run_workbench_command", names)
        self.assertNotIn("core.propose_create_part_box", names)
        self.assertIn("part.get_objects", names)
        self.assertIn("part.create_primitive", names)
        self.assertIn("part.set_placement", names)
        self.assertIn("part.set_primitive_dimensions", names)
        self.assertIn("part.cut_cylindrical_hole", names)
        self.assertIn("part.apply_fillet", names)
        self.assertIn("part.apply_chamfer", names)
        self.assertIn("part.apply_thickness", names)
        self.assertNotIn("part.propose_create_primitive", names)

    def test_tool_shape_report_explains_available_and_missing_provider_capabilities(self):
        service = VibeCADService()
        report = service.tool_shape_report("PartDesignWorkbench")
        names = set(report["provider_tool_names"])
        self.assertEqual(report["active_workbench"], "PartDesignWorkbench")
        self.assertIn("core.get_tool_shape_report", names)
        self.assertIn("partdesign.create_sketch", names)
        self.assertIn("partdesign.pad_sketch", names)
        self.assertIn("partdesign.pocket_sketch", names)
        self.assertIn("partdesign.hole_from_sketch", names)
        self.assertIn("partdesign.revolve_sketch", names)
        self.assertIn("partdesign.loft_profiles", names)
        self.assertIn("partdesign.sweep_profile", names)
        self.assertIn("partdesign.linear_pattern", names)
        self.assertIn("partdesign.polar_pattern", names)
        self.assertIn("partdesign.mirror_feature", names)
        self.assertIn("partdesign.fillet_feature", names)
        self.assertIn("partdesign.chamfer_feature", names)
        self.assertIn("partdesign.thickness_feature", names)
        self.assertIn("partdesign.set_feature_dimensions", names)
        self.assertIn("sketcher.add_line", names)
        self.assertIn("sketcher.add_circle", names)
        self.assertIn("sketcher.add_arc", names)
        self.assertIn("sketcher.add_slot", names)
        slot_schema = next(schema for schema in report["provider_tools"] if schema["name"] == "sketcher.add_slot")
        slot_properties = slot_schema["parameters"]["properties"]
        self.assertIn("overall_length", slot_properties)
        self.assertIn("center_distance", slot_properties)
        self.assertIn("length_mode", slot_properties)
        self.assertIn("overall end-to-end", slot_properties["length"]["description"])
        self.assertNotIn("length", slot_schema["parameters"]["required"])
        self.assertIn("sketcher.add_constraint", names)
        self.assertIn("core.delete_object", names)
        self.assertNotIn("part.create_primitive", names)
        self.assertNotIn("draft.create_array", names)
        self.assertNotIn("assembly.create_assembly", names)
        self.assertNotIn("techdraw.create_page", names)
        self.assertTrue(report["capabilities"]["atomic_sketch_geometry"]["available"])
        self.assertTrue(report["capabilities"]["atomic_sketch_constraints"]["available"])
        self.assertTrue(report["capabilities"]["iterative_delete"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_pad_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_pocket_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_hole_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_revolution_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_groove_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_loft_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_sweep_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_helix_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_pattern_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_mirror_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_datum_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_draft_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_boolean_features"]["available"])
        self.assertTrue(report["capabilities"]["partdesign_edge_finishing"]["available"])
        self.assertTrue(report["capabilities"]["sketch_dimension_edits"]["available"])
        self.assertTrue(report["capabilities"]["sketcher_profile_validation"]["available"])
        self.assertTrue(report["capabilities"]["sketcher_solver_diagnosis"]["available"])
        self.assertTrue(report["capabilities"]["sketcher_external_geometry"]["available"])
        self.assertTrue(report["capabilities"]["sketcher_curve_editing"]["available"])
        self.assertTrue(report["capabilities"]["sketcher_detailed_constraints"]["available"])
        self.assertFalse(report["capabilities"]["part_primitives"]["available"])
        self.assertTrue(report["capabilities"]["shells_and_wall_thickness"]["available"])
        self.assertFalse(report["capabilities"]["edge_chamfering"]["available"])
        self.assertFalse(report["capabilities"]["detail_drawings"]["available"])
        self.assertFalse(report["capabilities"]["assembly_component_add"]["available"])
        coverage = {
            item["tool_class"]: item
            for item in report["sketcher_human_command_coverage"]
        }
        self.assertEqual(
            coverage["Sketcher curve repair and local editing"]["coverage"],
            "covered",
        )
        self.assertEqual(
            coverage["Sketcher external/reference geometry"]["coverage"],
            "partial",
        )
        self.assertIn(
            "sketcher.carbon_copy",
            coverage["Sketcher external/reference geometry"]["missing_desired_tools"],
        )
        self.assertEqual(
            coverage["Sketcher bulk transform and duplicate operations"]["coverage"],
            "partial",
        )
        self.assertIn(
            "sketcher.transform_geometry",
            coverage["Sketcher bulk transform and duplicate operations"]["available_provider_tools"],
        )
        self.assertIn(
            "sketcher.copy_geometry",
            coverage["Sketcher bulk transform and duplicate operations"]["available_provider_tools"],
        )
        self.assertIn(
            "sketcher.rectangular_array",
            coverage["Sketcher bulk transform and duplicate operations"]["available_provider_tools"],
        )
        self.assertIn(
            "sketcher.offset_geometry",
            coverage["Sketcher offset and derived-profile operations"]["available_provider_tools"],
        )
        self.assertIn(
            "sketcher.mirror_geometry",
            coverage["Sketcher offset and derived-profile operations"]["available_provider_tools"],
        )
        self.assertEqual(
            coverage["Sketcher offset and derived-profile operations"]["coverage"],
            "covered",
        )
        self.assertNotIn(
            "sketcher.copy_geometry",
            coverage["Sketcher bulk transform and duplicate operations"]["missing_desired_tools"],
        )
        self.assertNotIn(
            "sketcher.rectangular_array",
            coverage["Sketcher bulk transform and duplicate operations"]["missing_desired_tools"],
        )
        self.assertIn(
            "sketcher.delete_all_geometry",
            coverage["Sketcher bulk deletion and cleanup"]["available_provider_tools"],
        )
        self.assertIn(
            "sketcher.delete_all_constraints",
            coverage["Sketcher bulk deletion and cleanup"]["available_provider_tools"],
        )
        self.assertEqual(
            coverage["Sketcher bulk deletion and cleanup"]["missing_desired_tools"],
            ["sketcher.remove_axes_alignment"],
        )
        self.assertNotIn(
            "Sketcher trim/extend, external geometry references, and named datum lookup",
            report["still_missing_tool_classes"],
        )
        self.assertIn("still_missing_tool_classes", report)
        self.assertIn("why_results_can_be_primitive", report)
        self.assertGreaterEqual(report["human_workbench_command_count"], 0)

    def test_provider_can_report_tool_shape_gaps_during_run(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service, "PartDesignWorkbench")
        result = runner(
            "core.report_tool_shape_gap",
            json.dumps(
                {
                    "missing_capability": "parametric NEMA17 mounting-hole sketch helper",
                    "why_needed": "Robot motor mounts need constrained hole layout workflows.",
                    "desired_native_tool": "partdesign.create_mounting_hole_sketch",
                    "current_workaround": "manual sketch constraints",
                    "active_workbench": "PartDesignWorkbench",
                }
            ),
        )
        self.assertTrue(result["ok"], result)
        self.assertIn("feedback_id", result["result"])
        self.assertIn("recent_feedback", result["result"])
        report = service.tool_shape_report("PartDesignWorkbench")
        feedback = report["recent_tool_shape_feedback"]
        self.assertTrue(feedback)
        self.assertEqual(
            feedback[-1]["desired_native_tool"],
            "partdesign.create_mounting_hole_sketch",
        )

    def test_provider_can_report_tool_shape_gap_with_model_preferred_fields(self):
        service = VibeCADService()
        runner = make_provider_tool_runner(service, "SketcherWorkbench")
        result = runner(
            "core.report_tool_shape_gap",
            json.dumps(
                {
                    "tool_or_class": "sketcher.offset_geometry",
                    "severity": "high",
                    "why_blocks_quality": "Offset is needed for wall thickness and clearance profiles.",
                    "needed_schema": "geometry_handles, offset_distance, side, join_style",
                    "needed_result_data": "created_geometry_indices, old_to_new_geometry_index, solver_status",
                    "active_workbench": "SketcherWorkbench",
                }
            ),
        )
        self.assertTrue(result["ok"], result)
        recorded = result["result"]["recorded"]
        self.assertEqual(recorded["missing_capability"], "sketcher.offset_geometry")
        self.assertEqual(recorded["desired_native_tool"], "sketcher.offset_geometry")
        self.assertEqual(recorded["severity"], "high")
        self.assertIn("created_geometry_indices", recorded["needed_result_data"])

    def test_provider_tool_runner_can_create_detailed_part_features(self):
        if not _gui_workbench_api_available():
            self.skipTest("FreeCAD GUI workbench API unavailable")
        import FreeCAD as App

        doc = App.newDocument("VibeCADDetailedPartTools")
        try:
            service = VibeCADService()
            runner = make_provider_tool_runner(service, "PartWorkbench")
            base = runner(
                "part.create_primitive",
                '{"primitive_type": "box", "label": "Motor plate", "length": 60, "width": 40, "height": 5}',
            )
            self.assertTrue(base["ok"], base)
            moved = runner(
                "part.set_placement",
                '{"object_name": "Motor plate", "x": 10, "y": 5, "z": 2, "yaw_degrees": 15}',
            )
            self.assertTrue(moved["ok"], moved)
            resized = runner(
                "part.set_primitive_dimensions",
                '{"object_name": "Motor plate", "length": 70, "width": 45}',
            )
            self.assertTrue(resized["ok"], resized)
            cut = runner(
                "part.cut_cylindrical_hole",
                '{"target_name": "Motor plate", "label": "Motor plate center bore", "radius": 4, "depth": 12, "x": 30, "y": 20, "z": -3, "axis": "Z"}',
            )
            self.assertTrue(cut["ok"], cut)
            switched_to_draft = runner("core.activate_workbench", '{"name": "DraftWorkbench"}')
            self.assertTrue(switched_to_draft["ok"], switched_to_draft)
            array = runner(
                "draft.create_array",
                '{"object_name": "Motor plate center bore", "label": "Motor plate bore pattern", "array_type": "polar", "polar_count": 4, "polar_angle": 360, "center_x": 30, "center_y": 20, "center_z": 0}',
            )
            self.assertTrue(array["ok"], array)
            switched_to_part = runner("core.activate_workbench", '{"name": "PartWorkbench"}')
            self.assertTrue(switched_to_part["ok"], switched_to_part)
            fillet = runner(
                "part.apply_fillet",
                '{"object_name": "Motor plate center bore", "label": "Rounded motor plate", "radius": 0.5, "edge_indices": [1, 2, 3, 4]}',
            )
            self.assertTrue(fillet["ok"], fillet)
            chamfer = runner(
                "part.apply_chamfer",
                '{"object_name": "Motor plate", "label": "Chamfered motor plate", "distance": 0.5, "edge_indices": [1, 2, 3, 4]}',
            )
            self.assertTrue(chamfer["ok"], chamfer)
            thickness = runner(
                "part.apply_thickness",
                '{"object_name": "Motor plate", "label": "Hollow motor plate", "wall_thickness": 1.0, "face_names": ["Face6"], "inward": true}',
            )
            self.assertTrue(thickness["ok"], thickness)

            labels = {getattr(obj, "Label", obj.Name) for obj in doc.Objects}
            self.assertIn("Motor plate", labels)
            self.assertIn("Motor plate center bore", labels)
            self.assertIn("Motor plate bore pattern", labels)
            self.assertIn("Rounded motor plate", labels)
            self.assertIn("Chamfered motor plate", labels)
            self.assertIn("Hollow motor plate", labels)
            plate = next(obj for obj in doc.Objects if getattr(obj, "Label", "") == "Motor plate")
            self.assertAlmostEqual(float(plate.Length), 70.0)
            self.assertAlmostEqual(float(plate.Width), 45.0)
            pattern = next(
                obj
                for obj in doc.Objects
                if getattr(obj, "Label", "") == "Motor plate bore pattern"
            )
            self.assertIn("Array", getattr(pattern, "Proxy", pattern).__class__.__name__)
            rounded = next(
                obj
                for obj in doc.Objects
                if getattr(obj, "Label", "") == "Rounded motor plate"
            )
            self.assertGreater(len(getattr(rounded.Shape, "Faces", [])), 0)
            self.assertGreater(float(getattr(rounded.Shape, "Volume", 0.0)), 0.0)
            chamfered = next(
                obj
                for obj in doc.Objects
                if getattr(obj, "Label", "") == "Chamfered motor plate"
            )
            self.assertGreater(len(getattr(chamfered.Shape, "Faces", [])), 0)
            self.assertGreater(float(getattr(chamfered.Shape, "Volume", 0.0)), 0.0)
            hollow = next(
                obj
                for obj in doc.Objects
                if getattr(obj, "Label", "") == "Hollow motor plate"
            )
            self.assertEqual(hollow.TypeId, "Part::Thickness")
            self.assertEqual(hollow.Faces[0], plate)
            self.assertIn("Face6", hollow.Faces[1])
            self.assertLess(float(hollow.Value), 0.0)
            self.assertGreater(len(getattr(hollow.Shape, "Faces", [])), 0)
            self.assertGreater(float(getattr(hollow.Shape, "Volume", 0.0)), 0.0)
        finally:
            App.closeDocument(doc.Name)

    def test_test_workbench_tool_pack_scopes_commands(self):
        service = VibeCADService()
        summary = service.workbench_command_summary("TestWorkbench")
        self.assertEqual(summary["active_workbench"], "TestWorkbench")
        self.assertEqual(summary["command_prefixes"], ["Test_", "Std_Test"])
        self.assertIn("commands", summary)
        templates = service.workbench_object_templates("TestWorkbench")
        self.assertIn({"name": "test_group", "object_type": "App::DocumentObjectGroup"}, templates["templates"])

    def test_none_workbench_tool_pack_exposes_core_context(self):
        service = VibeCADService()
        summary = service.workbench_tool_pack_summary("NoneWorkbench")
        self.assertEqual(summary["tool_pack"]["workbench"], "NoneWorkbench")
        tools = service.provider_tool_surface("NoneWorkbench")
        names = {tool["name"] for tool in tools["tools"]}
        self.assertIn("core.get_active_document", names)
        self.assertNotIn("core.run_workbench_command", names)
        self.assertNotIn("core.propose_create_workbench_object", names)
        self.assertNotIn("part.propose_create_primitive", names)

    def test_part_summary_reads_real_part_objects(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForPartSummary")
            box.Label = "Readable Part Box"
            box.Length = 2
            box.Width = 3
            box.Height = 4
            doc.recompute()
            service = VibeCADService()
            summary = service.part_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Part Box")
            self.assertEqual(summary["objects"][0]["type"], "Part::Box")
            self.assertIn("shape", summary["objects"][0])
        finally:
            App.closeDocument(doc.Name)

    def test_document_summary_includes_shape_and_link_metadata_for_detail_features(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDocumentDetailSummaryTest")
        try:
            base = doc.addObject("Part::Box", "DetailSummaryBase")
            base.Label = "Detail Summary Plate"
            base.Length = 30
            base.Width = 20
            base.Height = 4
            tool = doc.addObject("Part::Cylinder", "DetailSummaryHoleTool")
            tool.Label = "Detail Summary Hole Tool"
            tool.Radius = 3
            tool.Height = 10
            tool.Placement.Base.z = -3
            cut = doc.addObject("Part::Cut", "DetailSummaryCut")
            cut.Label = "Detail Summary Cut"
            cut.Base = base
            cut.Tool = tool
            doc.recompute()

            service = VibeCADService()
            summary = service.document_summary()
            cut_summary = next(
                item
                for item in summary["objects"]
                if item["name"] == cut.Name
            )
            self.assertEqual(cut_summary["type"], "Part::Cut")
            self.assertEqual(cut_summary["base"]["name"], base.Name)
            self.assertEqual(cut_summary["tool"]["name"], tool.Name)
            self.assertGreater(cut_summary["shape"]["faces"], 0)
            self.assertGreater(cut_summary["shape"]["edges"], 0)
            self.assertGreater(cut_summary["shape"]["volume"], 0.0)
            self.assertEqual(cut_summary["placement"]["base"], [0.0, 0.0, 0.0])
            self.assertIn("bound_box", cut_summary)
        finally:
            App.closeDocument(doc.Name)

    def test_document_summary_includes_material_appearance_state(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDocumentMaterialSummaryTest")
        try:
            box = doc.addObject("Part::Box", "MaterialSummaryBox")
            box.Label = "Material Summary Box"
            service = VibeCADService()
            result = service.registry.call(
                "material.apply_appearance",
                object_name=box.Name,
                diffuse_color=[0.1, 0.4, 0.8],
                transparency=0.45,
            )
            self.assertTrue(result["ok"], result)
            summary = service.document_summary()
            box_summary = next(
                item
                for item in summary["objects"]
                if item["name"] == box.Name
            )
            self.assertEqual(box_summary["material"]["name"], "VibeCAD Appearance")
            self.assertEqual(
                box_summary["material"]["diffuse_color"],
                "(0.1000, 0.4000, 0.8000, 1.0)",
            )
            self.assertAlmostEqual(box_summary["material"]["transparency"], 0.45)
        finally:
            App.closeDocument(doc.Name)

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
                "part.create_primitive",
                '{"primitive_type": "nonsense", "label": "Bad primitive"}',
            )["ok"]
        )

    def test_mesh_summary_reads_real_mesh(self):
        import FreeCAD as App
        import Mesh

        doc = App.newDocument("VibeCADMeshSummaryTest")
        try:
            obj = doc.addObject("Mesh::Feature", "MeshForSummary")
            obj.Label = "Readable Mesh"
            obj.Mesh = Mesh.createBox(1.0, 2.0, 3.0)
            doc.recompute()
            service = VibeCADService()
            summary = service.mesh_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Mesh")
            self.assertEqual(summary["objects"][0]["mesh"]["facets"], 12)
            self.assertIn("bound_box", summary["objects"][0]["mesh"])
        finally:
            App.closeDocument(doc.Name)

    def test_points_summary_reads_real_points(self):
        import FreeCAD as App
        import Points

        doc = App.newDocument("VibeCADPointsSummaryTest")
        try:
            obj = doc.addObject("Points::Feature", "PointsForSummary")
            obj.Label = "Readable Points"
            kernel = Points.Points()
            kernel.addPoints([
                App.Vector(0, 0, 0),
                App.Vector(1, 2, 3),
            ])
            obj.Points = kernel
            doc.recompute()
            service = VibeCADService()
            summary = service.points_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Points")
            self.assertEqual(summary["objects"][0]["point_count"], 2)
            self.assertIn("bound_box", summary["objects"][0])
        finally:
            App.closeDocument(doc.Name)

    def test_material_summary_reads_shape_material_objects(self):
        import FreeCAD as App
        import Materials

        doc = App.newDocument("VibeCADMaterialSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMaterialSummary")
            material = Materials.Material()
            material.Name = "Readable Material"
            material.addAppearanceModel(Materials.UUIDs().BasicRendering)
            material.setAppearanceValue("DiffuseColor", "(0.2000, 0.4000, 0.6000, 1.0)")
            material.setAppearanceValue("Transparency", "0.25")
            box.ShapeMaterial = material
            doc.recompute()
            service = VibeCADService()
            summary = service.material_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["material_name"], "Readable Material")
            self.assertEqual(summary["objects"][0]["diffusecolor"], "(0.2000, 0.4000, 0.6000, 1.0)")
            self.assertEqual(summary["objects"][0]["transparency"], 0.25)
        finally:
            App.closeDocument(doc.Name)

    def test_apply_material_appearance_applies_directly_for_provider_loop(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADMaterialDirectApplyTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMaterialDirectApply")
            service = VibeCADService()
            result = service.registry.call(
                "material.apply_appearance",
                object_name=box.Name,
                diffuse_color=[0.7, 0.2, 0.1],
                transparency=0.35,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                box.ShapeMaterial.getAppearanceValue("DiffuseColor"),
                "(0.7000, 0.2000, 0.1000, 1.0)",
            )
            self.assertAlmostEqual(float(box.ShapeMaterial.getAppearanceValue("Transparency")), 0.35)
            transaction_result = result["transaction"]["result"]
            self.assertEqual(transaction_result["object"], box.Name)
            self.assertEqual(transaction_result["diffuse_color"], "(0.7000, 0.2000, 0.1000, 1.0)")
            self.assertAlmostEqual(transaction_result["transparency"], 0.35)
        finally:
            App.closeDocument(doc.Name)

    def test_sketcher_summary_reads_real_sketch(self):
        import FreeCAD as App
        import Part

        doc = App.newDocument("VibeCADSketcherSummaryTest")
        try:
            sketch = doc.addObject("Sketcher::SketchObject", "SketchForSummary")
            sketch.addGeometry(
                Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)),
                False,
            )
            doc.recompute()
            service = VibeCADService()
            summary = service.sketcher_summary(sketch.Name)
            self.assertTrue(summary["found"])
            self.assertEqual(summary["sketch"]["name"], sketch.Name)
            self.assertEqual(summary["geometry_count"], 1)
            self.assertEqual(summary["geometry"][0]["type"], "LineSegment")
        finally:
            App.closeDocument(doc.Name)

    def test_spreadsheet_summary_reads_real_sheet(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSpreadsheetSummaryTest")
        try:
            sheet = doc.addObject("Spreadsheet::Sheet", "SheetForSummary")
            sheet.set("A1", "42")
            sheet.set("B2", "=A1")
            doc.recompute()
            service = VibeCADService()
            summary = service.spreadsheet_summary(sheet.Name)
            self.assertTrue(summary["found"])
            self.assertEqual(summary["sheet"]["name"], sheet.Name)
            cells = {item["cell"]: item for item in summary["cells"]}
            self.assertEqual(cells["A1"]["contents"], "42")
            self.assertEqual(cells["B2"]["contents"], "=A1")
        finally:
            App.closeDocument(doc.Name)

    def test_draft_summary_reads_real_draft_line(self):
        import FreeCAD as App
        import Draft

        doc = App.newDocument("VibeCADDraftSummaryTest")
        try:
            line = Draft.make_line(App.Vector(0, 0, 0), App.Vector(5, 0, 0))
            line.Label = "Readable Draft Line"
            doc.recompute()
            service = VibeCADService()
            summary = service.draft_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["label"], "Readable Draft Line")
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_summary_reads_real_body_and_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignSummaryTest")
        try:
            body = doc.addObject("PartDesign::Body", "BodyForSummary")
            body.Label = "Readable Body"
            feature = body.newObject("PartDesign::AdditiveBox", "BoxForSummary")
            feature.Label = "Readable Additive Box"
            doc.recompute()
            service = VibeCADService()
            summary = service.partdesign_summary(body.Name)
            self.assertEqual(summary["body_count"], 1)
            self.assertEqual(summary["selected"]["name"], body.Name)
            self.assertEqual(summary["selected"]["label"], "Readable Body")
            self.assertEqual(summary["selected"]["feature_count"], 1)
            self.assertEqual(summary["selected"]["features"][0]["name"], feature.Name)
            self.assertEqual(summary["selected"]["tip"]["name"], feature.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_create_partdesign_sketch_uses_default_xy_plane_without_picker(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignDefaultSketchTest")
        try:
            service = VibeCADService()
            result = service.registry.call("partdesign.create_sketch", label="AI Sketch")
            self.assertTrue(result["ok"], result)
            bodies = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]
            sketches = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"]
            self.assertEqual(len(bodies), 1)
            self.assertEqual(len(sketches), 1)
            self.assertEqual(sketches[0].Label, "AI Sketch")
            self.assertEqual(getattr(sketches[0], "MapMode", ""), "FlatFace")
            support = list(getattr(sketches[0], "AttachmentSupport", []) or [])
            self.assertTrue(support)
            self.assertEqual(getattr(support[0][0], "Name", ""), "XY_Plane")
            transaction_result = result["transaction"]["result"]
            self.assertEqual(transaction_result["plane"], "XY_Plane")
            self.assertEqual(transaction_result["sketch"], sketches[0].Name)
        finally:
            App.closeDocument(doc.Name)

    def test_set_sketcher_constraint_value_edits_existing_dimension(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchConstraintEditTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Editable Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call("sketcher.draw_rectangle",
                width=10,
                height=5,
                sketch_name=sketch.Name,
            )
            self.assertTrue(draw_result["ok"], draw_result)
            summary = service.sketcher_summary(sketch.Name)
            distance_constraints = [
                item for item in summary["constraints"]
                if item["type"] == "Distance" and abs(float(item.get("value", 0.0)) - 10.0) < 1e-6
            ]
            self.assertTrue(distance_constraints, summary["constraints"])
            edit_result = service.registry.call("sketcher.set_constraint_value",
                sketch_name=sketch.Name,
                constraint_index=distance_constraints[0]["index"],
                value=20,
            )
            self.assertTrue(edit_result["ok"], edit_result)
            edited = service.sketcher_summary(sketch.Name)
            edited_constraint = edited["constraints"][distance_constraints[0]["index"]]
            self.assertAlmostEqual(float(edited_constraint["value"]), 20.0)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_constraint_identity_tools_edit_design_intent(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchConstraintIdentityTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Named Constraint Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call(
                "sketcher.draw_rectangle",
                width=30,
                height=12,
                sketch_name=sketch.Name,
            )
            self.assertTrue(draw_result["ok"], draw_result)

            summary = service.registry.call("sketcher.list_constraints", sketch_name=sketch.Name)
            self.assertTrue(summary["ok"], summary)
            width_constraints = [
                item for item in summary["constraints"]
                if item["type"] == "Distance" and abs(float(item.get("value", 0.0)) - 30.0) < 1e-6
            ]
            self.assertTrue(width_constraints, summary["constraints"])
            width_index = width_constraints[0]["index"]

            rename_result = service.registry.call(
                "sketcher.set_constraint_name",
                sketch_name=sketch.Name,
                constraint_index=width_index,
                constraint_name="Width",
            )
            self.assertTrue(rename_result["ok"], rename_result)
            lookup_result = service.registry.call(
                "sketcher.get_constraint_by_name",
                sketch_name=sketch.Name,
                constraint_name="Width",
            )
            self.assertTrue(lookup_result["ok"], lookup_result)
            self.assertEqual(lookup_result["constraint_index"], width_index)
            self.assertEqual(lookup_result["constraint"]["name"], "Width")

            edit_result = service.registry.call(
                "sketcher.set_constraint_value_by_name",
                sketch_name=sketch.Name,
                constraint_name="Width",
                value=42,
            )
            self.assertTrue(edit_result["ok"], edit_result)
            edited_lookup = service.registry.call(
                "sketcher.get_constraint_by_name",
                sketch_name=sketch.Name,
                constraint_name="Width",
            )
            self.assertAlmostEqual(float(edited_lookup["constraint"]["value"]), 42.0)

            expression_result = service.registry.call(
                "sketcher.set_constraint_expression",
                sketch_name=sketch.Name,
                constraint_index=width_index,
                expression="21 * 2",
            )
            self.assertTrue(expression_result["ok"], expression_result)
            expression_summary = service.registry.call("sketcher.list_constraints", sketch_name=sketch.Name)
            width_after_expression = [
                item for item in expression_summary["constraints"]
                if item.get("name") == "Width"
            ][0]
            self.assertIn("expression", width_after_expression)

            driving_result = service.registry.call(
                "sketcher.set_constraint_driving",
                sketch_name=sketch.Name,
                constraint_index=width_index,
                driving=False,
            )
            self.assertTrue(driving_result["ok"], driving_result)
            reference_lookup = service.registry.call(
                "sketcher.get_constraint_by_name",
                sketch_name=sketch.Name,
                constraint_name="Width",
            )
            self.assertFalse(reference_lookup["constraint"]["driving"])
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_geometry_identity_tools_target_named_geometry(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchGeometryIdentityTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Named Geometry Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            line_result = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=25,
                end_y=0,
            )
            self.assertTrue(line_result["ok"], line_result)
            name_result = service.registry.call(
                "sketcher.set_geometry_name",
                sketch_name=sketch.Name,
                geometry_index=0,
                geometry_name="base_edge",
            )
            self.assertTrue(name_result["ok"], name_result)
            self.assertEqual(name_result["transaction"]["result"]["semantic_handle"], "name:base_edge")

            inventory = service.registry.call("sketcher.list_geometry", sketch_name=sketch.Name)
            self.assertTrue(inventory["ok"], inventory)
            self.assertEqual(inventory["named_geometry"]["base_edge"]["geometry_index"], 0)
            self.assertIn("name:base_edge", inventory["geometry"][0]["semantic_handles"])

            resolved = service.registry.call(
                "sketcher.resolve_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
            )
            self.assertTrue(resolved["ok"], resolved)
            self.assertEqual(resolved["geometry_index"], 0)

            horizontal = service.registry.call(
                "sketcher.constrain_horizontal",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
            )
            self.assertTrue(horizontal["ok"], horizontal)
            distance = service.registry.call(
                "sketcher.constrain_distance",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
                value=25,
            )
            self.assertTrue(distance["ok"], distance)

            moved = service.registry.call(
                "sketcher.move_point",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
                point="whole",
                x=0,
                y=5,
                relative=True,
            )
            self.assertTrue(moved["ok"], moved)
            moved_inventory = service.registry.call("sketcher.list_geometry", sketch_name=sketch.Name)
            self.assertTrue(moved_inventory["named_geometry"]["base_edge"]["ok"], moved_inventory["named_geometry"])
            self.assertTrue(moved_inventory["named_geometry"]["base_edge"]["fingerprint_changed"])

            name_again = service.registry.call(
                "sketcher.set_geometry_name",
                sketch_name=sketch.Name,
                geometry_index=0,
                geometry_name="base_edge",
            )
            self.assertTrue(name_again["ok"], name_again)
            construction = service.registry.call(
                "sketcher.set_construction",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
                construction=True,
            )
            self.assertTrue(construction["ok"], construction)

            delete_result = service.registry.call(
                "sketcher.delete_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
            )
            self.assertTrue(delete_result["ok"], delete_result)
            stale = service.registry.call(
                "sketcher.resolve_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
            )
            self.assertFalse(stale["ok"], stale)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_semantic_constraint_tools_use_handles_and_references(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchSemanticConstraintTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Semantic Constraint Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            base = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=10,
                start_y=10,
                end_x=30,
                end_y=10,
            )
            self.assertTrue(base["ok"], base)
            upright = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=40,
                start_y=0,
                end_x=40,
                end_y=20,
            )
            self.assertTrue(upright["ok"], upright)
            circle = service.registry.call(
                "sketcher.add_circle",
                sketch_name=sketch.Name,
                center_x=60,
                center_y=10,
                radius=5,
            )
            self.assertTrue(circle["ok"], circle)

            for index, name in ((0, "base_edge"), (1, "upright_edge"), (2, "locator_circle")):
                named = service.registry.call(
                    "sketcher.set_geometry_name",
                    sketch_name=sketch.Name,
                    geometry_index=index,
                    geometry_name=name,
                )
                self.assertTrue(named["ok"], named)

            lock = service.registry.call(
                "sketcher.constrain_lock_point",
                sketch_name=sketch.Name,
                geometry_handle="name:base_edge",
                point="start",
                x=10,
                y=10,
            )
            self.assertTrue(lock["ok"], lock)
            point_distance = service.registry.call(
                "sketcher.constrain_distance_points",
                sketch_name=sketch.Name,
                first_geometry_handle="name:base_edge",
                first_point="start",
                second_geometry_handle="origin",
                second_point="origin",
                value=14.1421356237,
            )
            self.assertTrue(point_distance["ok"], point_distance)
            point_on_axis = service.registry.call(
                "sketcher.constrain_point_on_reference",
                sketch_name=sketch.Name,
                point_geometry_handle="name:upright_edge",
                point="start",
                reference_geometry_handle="axis:H",
            )
            self.assertTrue(point_on_axis["ok"], point_on_axis)
            angle = service.registry.call(
                "sketcher.constrain_angle_between",
                sketch_name=sketch.Name,
                first_geometry_handle="name:base_edge",
                second_geometry_handle="name:upright_edge",
                angle_degrees=90,
            )
            self.assertTrue(angle["ok"], angle)
            block = service.registry.call(
                "sketcher.constrain_block_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:locator_circle",
            )
            self.assertTrue(block["ok"], block)

            summary = service.registry.call("sketcher.list_constraints", sketch_name=sketch.Name)
            self.assertTrue(summary["ok"], summary)
            types = [item["type"] for item in summary["constraints"]]
            self.assertIn("DistanceX", types)
            self.assertIn("DistanceY", types)
            self.assertIn("Distance", types)
            self.assertIn("PointOnObject", types)
            self.assertIn("Angle", types)
            self.assertIn("Block", types)
            point_on_object = [item for item in summary["constraints"] if item["type"] == "PointOnObject"][-1]
            self.assertEqual(point_on_object["second"], -1)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_legacy_tools_accept_semantic_handles(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchLegacyHandleTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Legacy Handle Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            lines = [
                ("line_a", (0, 0, 20, 0)),
                ("line_b", (0, 5, 20, 5)),
                ("line_c", (30, 0, 30, 15)),
                ("line_d", (40, 0, 40, 15)),
            ]
            for name, coords in lines:
                line = service.registry.call(
                    "sketcher.add_line",
                    sketch_name=sketch.Name,
                    start_x=coords[0],
                    start_y=coords[1],
                    end_x=coords[2],
                    end_y=coords[3],
                )
                self.assertTrue(line["ok"], line)
                named = service.registry.call(
                    "sketcher.set_geometry_name",
                    sketch_name=sketch.Name,
                    geometry_index=line["transaction"]["result"]["geometry_index"],
                    geometry_name=name,
                )
                self.assertTrue(named["ok"], named)

            parallel = service.registry.call(
                "sketcher.constrain_parallel",
                sketch_name=sketch.Name,
                first_geometry_handle="name:line_a",
                second_geometry_handle="name:line_b",
            )
            self.assertTrue(parallel["ok"], parallel)
            perpendicular = service.registry.call(
                "sketcher.constrain_perpendicular",
                sketch_name=sketch.Name,
                first_geometry_handle="name:line_a",
                second_geometry_handle="name:line_c",
            )
            self.assertTrue(perpendicular["ok"], perpendicular)
            equal = service.registry.call(
                "sketcher.constrain_equal",
                sketch_name=sketch.Name,
                first_geometry_handle="name:line_c",
                second_geometry_handle="name:line_d",
            )
            self.assertTrue(equal["ok"], equal)
            coincident = service.registry.call(
                "sketcher.constrain_coincident",
                sketch_name=sketch.Name,
                first_geometry_handle="name:line_a",
                first_point="start",
                second_geometry_handle="origin",
                second_point="origin",
            )
            self.assertTrue(coincident["ok"], coincident)
            symmetric = service.registry.call(
                "sketcher.constrain_symmetric",
                sketch_name=sketch.Name,
                first_geometry_handle="name:line_c",
                first_point="start",
                second_geometry_handle="name:line_d",
                second_point="start",
                axis_or_center_geometry_handle="axis:V",
                axis_or_center_point="whole",
            )
            self.assertTrue(symmetric["ok"], symmetric)

            dimension = service.registry.call(
                "sketcher.constrain_distance",
                sketch_name=sketch.Name,
                geometry_handle="name:line_b",
                value=20,
            )
            self.assertTrue(dimension["ok"], dimension)
            dimension_index = dimension["transaction"]["result"]["constraint_index"]
            named_dimension = service.registry.call(
                "sketcher.set_constraint_name",
                sketch_name=sketch.Name,
                constraint_index=dimension_index,
                constraint_name="LineBLength",
            )
            self.assertTrue(named_dimension["ok"], named_dimension)
            expression = service.registry.call(
                "sketcher.set_constraint_expression",
                sketch_name=sketch.Name,
                constraint_name="LineBLength",
                expression="10 + 10",
            )
            self.assertTrue(expression["ok"], expression)
            driving = service.registry.call(
                "sketcher.set_constraint_driving",
                sketch_name=sketch.Name,
                constraint_name="LineBLength",
                driving=False,
            )
            self.assertTrue(driving["ok"], driving)
            deleted = service.registry.call(
                "sketcher.delete_constraint",
                sketch_name=sketch.Name,
                constraint_name="LineBLength",
            )
            self.assertTrue(deleted["ok"], deleted)

            summary = service.registry.call("sketcher.list_constraints", sketch_name=sketch.Name)
            self.assertTrue(summary["ok"], summary)
            constraint_types = [item["type"] for item in summary["constraints"]]
            for constraint_type in ("Parallel", "Perpendicular", "Equal", "Coincident", "Symmetric"):
                self.assertIn(constraint_type, constraint_types)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_topology_edit_tools_accept_geometry_handles(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchTopologyHandleTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Topology Handle Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            line = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=20,
                end_y=0,
            )
            self.assertTrue(line["ok"], line)
            named = service.registry.call(
                "sketcher.set_geometry_name",
                sketch_name=sketch.Name,
                geometry_index=0,
                geometry_name="editable_line",
            )
            self.assertTrue(named["ok"], named)
            split = service.registry.call(
                "sketcher.split_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:editable_line",
                x=10,
                y=0,
            )
            self.assertTrue(split["ok"], split)
            renamed = service.registry.call(
                "sketcher.set_geometry_name",
                sketch_name=sketch.Name,
                geometry_index=0,
                geometry_name="editable_segment",
            )
            self.assertTrue(renamed["ok"], renamed)
            trim = service.registry.call(
                "sketcher.trim_geometry",
                sketch_name=sketch.Name,
                geometry_handle="name:editable_segment",
                x=5,
                y=0,
            )
            self.assertTrue(trim["ok"], trim)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_create_open_solver_and_profile_tools(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchLifecycleTest")
        try:
            service = VibeCADService()
            create_result = service.registry.call(
                "sketcher.create_sketch",
                label="Lifecycle Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(create_result["ok"], create_result)
            sketch_name = create_result["active_sketch"]
            sketch = doc.getObject(sketch_name)
            self.assertIsNotNone(sketch)
            self.assertEqual(sketch.Label, "Lifecycle Sketch")
            self.assertIn("solver_status", create_result)
            self.assertIn("profile_validation", create_result)

            open_result = service.registry.call("sketcher.open_sketch", sketch_name=sketch_name)
            self.assertTrue(open_result["ok"], open_result)
            self.assertEqual(open_result["active_sketch"], sketch_name)

            close_result = service.registry.call("sketcher.close_sketch", sketch_name=sketch_name)
            self.assertTrue(close_result["ok"], close_result)
            self.assertEqual(close_result["active_sketch"], sketch_name)
            self.assertIn("task_panel", close_result)
            self.assertIn("solver_status", close_result)
            self.assertIn("profile_validation", close_result)

            line_result = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch_name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(line_result["ok"], line_result)
            self.assertIn("solver_status", line_result)
            self.assertIn("profile_validation", line_result)

            solver = service.registry.call("sketcher.get_solver_status", sketch_name=sketch_name)
            self.assertTrue(solver["ok"], solver)
            self.assertEqual(solver["sketch"], sketch_name)
            self.assertEqual(solver["geometry_count"], 1)

            profile = service.registry.call("sketcher.validate_profile", sketch_name=sketch_name)
            self.assertTrue(profile["ok"], profile)
            self.assertFalse(profile["closed_profile"])
            self.assertGreaterEqual(profile["open_endpoint_count"], 2)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_deep_profile_and_constraint_diagnostics(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchDeepDiagnosticsTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call(
                "sketcher.create_sketch",
                label="Deep Diagnostics Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch_name = sketch_result["active_sketch"]
            line = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch_name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(line["ok"], line)

            profile = service.registry.call("sketcher.validate_profile_deep", sketch_name=sketch_name)
            self.assertTrue(profile["ok"], profile)
            self.assertFalse(profile["closed_profile"])
            self.assertEqual(profile["nonconstruction_edge_count"], 1)
            self.assertGreaterEqual(len(profile["open_nodes"]), 2)
            blocker_kinds = {item["kind"] for item in profile["feature_readiness"]["blockers"]}
            self.assertIn("open_endpoints", blocker_kinds)
            self.assertIn("no_faces", blocker_kinds)
            self.assertFalse(profile["feature_readiness"]["pad"])

            diagnostics = service.registry.call("sketcher.diagnose_constraints", sketch_name=sketch_name)
            self.assertTrue(diagnostics["ok"], diagnostics)
            self.assertTrue(diagnostics["solver_status"]["under_constrained"], diagnostics)
            self.assertFalse(diagnostics["limits"]["exact_per_parameter_dof_available"])
            self.assertEqual(len(diagnostics["per_geometry_constraint_coverage"]), 1)
            self.assertTrue(diagnostics["suggested_next_checks"], diagnostics)
            suggested_kinds = {item["kind"] for item in diagnostics["suggested_next_checks"]}
            self.assertIn("close_endpoint", suggested_kinds)
            self.assertIn("solver_repair_actions", diagnostics)
            self.assertIn("next_actions", diagnostics)
        finally:
            App.closeDocument(doc.Name)

    def test_sketcher_solver_repair_actions_are_direct_tool_calls(self):
        from tool_impl.sketcher.common import solver_repair_actions

        sketch = types.SimpleNamespace(Name="Sketch")
        solver = {
            "conflicting_constraint_indices": [3],
            "redundant_constraint_indices": [8, 11],
        }
        constraints = [{"index": index, "handle": f"constraint:{index}", "type": "Distance"} for index in range(12)]

        actions = solver_repair_actions(sketch, solver, constraints)

        self.assertEqual([item["kind"] for item in actions], [
            "remove_conflicting_constraint",
            "remove_redundant_constraint",
            "remove_redundant_constraint",
        ])
        for action, index in zip(actions, [3, 8, 11]):
            self.assertEqual(action["tool"], "sketcher.delete_constraint")
            self.assertEqual(action["arguments"], {"sketch_name": "Sketch", "constraint_index": index})
            self.assertEqual(action["target_constraint"]["handle"], f"constraint:{index}")

    def test_atomic_sketcher_tools_add_geometry_and_constraints(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADAtomicSketchToolsTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Atomic Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            horizontal = service.registry.call("sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(horizontal["ok"], horizontal)
            self.assertEqual(horizontal["mutation"]["created_geometry_indices"], [0])
            self.assertEqual(horizontal["mutation"]["geometry_count"], 1)
            vertical = service.registry.call("sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=10,
                start_y=0,
                end_x=10,
                end_y=5,
            )
            self.assertTrue(vertical["ok"], vertical)
            circle = service.registry.call("sketcher.add_circle",
                sketch_name=sketch.Name,
                center_x=5,
                center_y=2.5,
                radius=2,
            )
            self.assertTrue(circle["ok"], circle)
            self.assertEqual(circle["mutation"]["created_geometry_indices"], [2])
            circle_next_tools = {
                item.get("tool")
                for item in circle["next_actions"]
                if isinstance(item, dict)
            }
            self.assertIn("sketcher.constrain_radius", circle_next_tools)
            self.assertIn("sketcher.constrain_lock_point", circle_next_tools)
            arc = service.registry.call("sketcher.add_arc",
                sketch_name=sketch.Name,
                center_x=0,
                center_y=0,
                radius=4,
                start_angle_degrees=0,
                end_angle_degrees=90,
            )
            self.assertTrue(arc["ok"], arc)
            slot = service.registry.call("sketcher.add_slot",
                sketch_name=sketch.Name,
                center_x=20,
                center_y=0,
                length=14,
                width=4,
            )
            self.assertTrue(slot["ok"], slot)
            self.assertEqual(slot["mutation"]["created_geometry_indices"], [4, 5, 6, 7])
            self.assertEqual(len(slot["mutation"]["created_constraint_indices"]), 4)
            self.assertGreaterEqual(slot["profile_status"]["edge_count"], 4)
            slot_next_tools = {
                item.get("tool")
                for item in slot["next_actions"]
                if isinstance(item, dict)
            }
            self.assertNotIn("sketcher.constrain_block_geometry", slot_next_tools)

            coincident_constraint = service.registry.call(
                "sketcher.constrain_coincident",
                sketch_name=sketch.Name,
                first_geometry=0,
                first_point="end",
                second_geometry=1,
                second_point="start",
            )
            self.assertTrue(coincident_constraint["ok"], coincident_constraint)
            horizontal_constraint = service.registry.call("sketcher.add_constraint",
                sketch_name=sketch.Name,
                constraint_type="Horizontal",
                first_geometry=0,
            )
            self.assertTrue(horizontal_constraint["ok"], horizontal_constraint)
            vertical_constraint = service.registry.call("sketcher.constrain_vertical",
                sketch_name=sketch.Name,
                geometry_index=1,
            )
            self.assertTrue(vertical_constraint["ok"], vertical_constraint)
            length_constraint = service.registry.call("sketcher.constrain_distance",
                sketch_name=sketch.Name,
                geometry_index=0,
                value=10,
            )
            self.assertTrue(length_constraint["ok"], length_constraint)
            radius_constraint = service.registry.call("sketcher.constrain_radius",
                sketch_name=sketch.Name,
                geometry_index=2,
                value=2,
            )
            self.assertTrue(radius_constraint["ok"], radius_constraint)
            self.assertEqual(len(radius_constraint["mutation"]["created_constraint_indices"]), 1)
            arc_radius_constraint = service.registry.call("sketcher.add_constraint",
                sketch_name=sketch.Name,
                constraint_type="Radius",
                first_geometry=3,
                value=4,
            )
            self.assertTrue(arc_radius_constraint["ok"], arc_radius_constraint)

            summary = service.sketcher_summary(sketch.Name)
            self.assertEqual(summary["geometry_count"], 8)
            self.assertGreaterEqual(summary["constraint_count"], 10)
            self.assertIn("handle", summary["geometry"][0])
            self.assertIn("handle", summary["constraints"][0])
            constraint_types = [item["type"] for item in summary["constraints"]]
            for constraint_type in ("Coincident", "Horizontal", "Vertical", "Distance", "Radius"):
                self.assertIn(constraint_type, constraint_types)
            geometry_types = [item["type"] for item in summary["geometry"]]
            self.assertIn("ArcOfCircle", geometry_types)
            self.assertGreaterEqual(geometry_types.count("ArcOfCircle"), 3)
            self.assertGreaterEqual(geometry_types.count("LineSegment"), 4)
        finally:
            App.closeDocument(doc.Name)

    def test_sketcher_slot_returns_partdesign_usable_profile(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSlotProfileReadinessTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Slot Profile")
            self.assertTrue(sketch_result["ok"], sketch_result)
            slot = service.registry.call(
                "sketcher.add_slot",
                sketch_name="Sketch",
                center_x=0,
                center_y=0,
                length=20,
                width=6,
            )
            self.assertTrue(slot["ok"], slot)
            profile = slot["profile_status"]
            slot_result = slot["transaction"]["result"]
            self.assertEqual(slot_result["overall_length"], 20.0)
            self.assertEqual(slot_result["center_distance"], 14.0)
            self.assertEqual(slot_result["straight_segment_length"], 14.0)
            self.assertEqual(slot_result["radius"], 3.0)
            self.assertEqual(slot_result["bounding_box"]["width"], 20.0)
            self.assertEqual(slot_result["bounding_box"]["height"], 6.0)
            self.assertEqual(profile["edge_count"], 4, profile)
            self.assertTrue(profile["closed_profile"], profile)
            self.assertTrue(profile["fully_constrained"], profile)
            self.assertTrue(profile["ready_for_pad"], profile)
            self.assertTrue(profile["ready_for_pocket"], profile)
            self.assertFalse(slot["solver_status"]["conflicting_constraint_indices"], slot)
            self.assertFalse(slot["solver_status"]["redundant_constraint_indices"], slot)
            next_tools = {
                item.get("tool")
                for item in slot["next_actions"]
                if isinstance(item, dict)
            }
            self.assertIn("partdesign.pocket_sketch", next_tools)
        finally:
            App.closeDocument(doc.Name)

    def test_sketcher_slot_accepts_explicit_center_distance(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSlotCenterDistanceTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Slot Center Distance")
            self.assertTrue(sketch_result["ok"], sketch_result)
            slot = service.registry.call(
                "sketcher.add_slot",
                sketch_name="Sketch",
                center_x=0,
                center_y=0,
                center_distance=14,
                width=6,
            )
            self.assertTrue(slot["ok"], slot)
            slot_result = slot["transaction"]["result"]
            self.assertEqual(slot_result["overall_length"], 20.0)
            self.assertEqual(slot_result["center_distance"], 14.0)
            self.assertEqual(slot_result["bounding_box"]["width"], 20.0)

            length_mode_slot = service.registry.call(
                "sketcher.add_slot",
                sketch_name="Sketch",
                center_x=40,
                center_y=0,
                length=14,
                length_mode="center_to_center",
                width=6,
            )
            self.assertTrue(length_mode_slot["ok"], length_mode_slot)
            mode_result = length_mode_slot["transaction"]["result"]
            self.assertEqual(mode_result["overall_length"], 20.0)
            self.assertEqual(mode_result["center_distance"], 14.0)
        finally:
            App.closeDocument(doc.Name)

    def test_delete_object_removes_existing_object_for_iteration(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDeleteObjectIterationTest")
        try:
            service = VibeCADService()
            create_result = service.registry.call(
                "part.create_primitive",
                primitive_type="box",
                label="Wrong Block",
                length=10,
                width=10,
                height=10,
            )
            self.assertTrue(create_result["ok"], create_result)
            object_name = create_result["transaction"]["result"]["object"]
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

    def test_native_sketcher_tools_create_edit_and_delete_geometry(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADNativeSketchToolsTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Native Tool Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            point = service.registry.call("sketcher.add_point", sketch_name=sketch.Name, x=1, y=2)
            self.assertTrue(point["ok"], point)
            polyline = service.registry.call(
                "sketcher.add_polyline",
                sketch_name=sketch.Name,
                points=[[0, 0], [10, 0], [10, 5], [0, 5]],
                closed=True,
            )
            self.assertTrue(polyline["ok"], polyline)
            self.assertEqual(
                polyline["transaction"]["result"]["point_dimension_constraints_added"],
                8,
            )
            ellipse = service.registry.call(
                "sketcher.add_ellipse",
                sketch_name=sketch.Name,
                center_x=20,
                center_y=5,
                major_radius=6,
                minor_radius=3,
                angle_degrees=15,
            )
            self.assertTrue(ellipse["ok"], ellipse)
            bspline = service.registry.call(
                "sketcher.add_bspline",
                sketch_name=sketch.Name,
                points=[[0, 10], [5, 14], [10, 10]],
                interpolate=True,
            )
            self.assertTrue(bspline["ok"], bspline)

            construction = service.registry.call(
                "sketcher.set_construction",
                sketch_name=sketch.Name,
                geometry_index=0,
                construction=True,
            )
            self.assertTrue(construction["ok"], construction)
            self.assertTrue(construction["transaction"]["result"]["after"])
            self.assertEqual(construction["mutation"]["modified_geometry_indices"], [0])

            delete_constraint = service.registry.call(
                "sketcher.delete_constraint",
                sketch_name=sketch.Name,
                constraint_index=0,
            )
            self.assertTrue(delete_constraint["ok"], delete_constraint)
            self.assertEqual(delete_constraint["mutation"]["deleted_constraint_indices"], [0])
            self.assertIn(
                "old_to_new_constraint_index",
                delete_constraint["transaction"]["result"],
            )
            delete_geometry = service.registry.call(
                "sketcher.delete_geometry",
                sketch_name=sketch.Name,
                geometry_index=0,
            )
            self.assertTrue(delete_geometry["ok"], delete_geometry)
            self.assertEqual(delete_geometry["mutation"]["deleted_geometry_indices"], [0])
            self.assertIn(
                "old_to_new_geometry_index",
                delete_geometry["transaction"]["result"],
            )

            summary = service.sketcher_summary(sketch.Name)
            geometry_types = [item["type"] for item in summary["geometry"]]
            self.assertIn("LineSegment", geometry_types)
            self.assertIn("Ellipse", geometry_types)
            self.assertIn("BSplineCurve", geometry_types)

            bulk_constraints = service.registry.call(
                "sketcher.delete_all_constraints",
                sketch_name=sketch.Name,
            )
            self.assertTrue(bulk_constraints["ok"], bulk_constraints)
            self.assertEqual(
                bulk_constraints["mutation"]["deleted_constraint_indices"],
                bulk_constraints["transaction"]["result"]["deleted_constraint_indices"],
            )
            self.assertEqual(bulk_constraints["sketcher"]["constraint_count"], 0)

            bulk_geometry = service.registry.call(
                "sketcher.delete_all_geometry",
                sketch_name=sketch.Name,
                delete_constraints_first=False,
            )
            self.assertTrue(bulk_geometry["ok"], bulk_geometry)
            self.assertEqual(bulk_geometry["sketcher"]["geometry_count"], 0)
            self.assertEqual(bulk_geometry["sketcher"]["constraint_count"], 0)
            self.assertEqual(bulk_geometry["transaction"]["result"]["old_to_new_geometry_index"], {})
        finally:
            App.closeDocument(doc.Name)

    def test_slot_tool_returns_forward_actions_when_profile_is_fully_defined(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSlotConstraintTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Slot Probe")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            slot = service.registry.call(
                "sketcher.add_slot",
                sketch_name=sketch.Name,
                center_x=20,
                center_y=0,
                length=14,
                width=4,
            )

            self.assertTrue(slot["ok"], slot)
            self.assertEqual(slot["profile_status"]["degrees_of_freedom"], 0)
            self.assertTrue(slot["profile_status"]["fully_constrained"])
            self.assertEqual(slot["solver_status"]["conflicting_constraint_indices"], [])
            self.assertEqual(slot["solver_repair_actions"], [])
            slot_next_tools = {
                item.get("tool")
                for item in slot["next_actions"]
                if isinstance(item, dict)
            }
            self.assertIn("partdesign.pocket_sketch", slot_next_tools)
            self.assertNotIn("sketcher.constrain_block_geometry", slot_next_tools)
            self.assertNotIn("sketcher.delete_constraint", slot_next_tools)
        finally:
            App.closeDocument(doc.Name)

    def test_polyline_points_create_solver_defined_profile(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPolylineConstraintTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Polyline Probe")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            polyline = service.registry.call(
                "sketcher.add_polyline",
                sketch_name=sketch.Name,
                points=[[0, 0], [10, 0], [10, 5], [0, 5]],
                closed=True,
            )

            self.assertTrue(polyline["ok"], polyline)
            self.assertEqual(polyline["profile_status"]["degrees_of_freedom"], 0)
            self.assertTrue(polyline["profile_status"]["fully_constrained"])
            self.assertEqual(polyline["transaction"]["result"]["constraints_added"], 12)
            self.assertEqual(
                polyline["transaction"]["result"]["point_dimension_constraints_added"],
                8,
            )
            self.assertEqual(polyline["solver_status"]["conflicting_constraint_indices"], [])
            self.assertEqual(polyline["solver_status"]["redundant_constraint_indices"], [])
            self.assertNotIn(
                "sketcher.constrain_block_geometry",
                [action.get("tool") for action in polyline.get("next_actions", [])],
            )
        finally:
            App.closeDocument(doc.Name)

    def test_typed_sketcher_constraint_and_move_tools_execute_natively(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTypedSketchConstraintToolsTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Typed Constraint Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]

            lines = [
                service.registry.call(
                    "sketcher.add_line",
                    sketch_name=sketch.Name,
                    start_x=0,
                    start_y=0,
                    end_x=10,
                    end_y=0,
                ),
                service.registry.call(
                    "sketcher.add_line",
                    sketch_name=sketch.Name,
                    start_x=0,
                    start_y=5,
                    end_x=10,
                    end_y=5,
                ),
                service.registry.call(
                    "sketcher.add_line",
                    sketch_name=sketch.Name,
                    start_x=5,
                    start_y=0,
                    end_x=5,
                    end_y=5,
                ),
                service.registry.call(
                    "sketcher.add_line",
                    sketch_name=sketch.Name,
                    start_x=20,
                    start_y=5,
                    end_x=30,
                    end_y=5,
                ),
            ]
            for result in lines:
                self.assertTrue(result["ok"], result)
            circle = service.registry.call(
                "sketcher.add_circle",
                sketch_name=sketch.Name,
                center_x=25,
                center_y=0,
                radius=5,
            )
            self.assertTrue(circle["ok"], circle)

            transform = service.registry.call(
                "sketcher.transform_geometry",
                sketch_name=sketch.Name,
                geometry_indices=[0, 1],
                dx=2,
                dy=3,
            )
            self.assertTrue(transform["ok"], transform)
            self.assertEqual(transform["mutation"]["modified_geometry_indices"], [0, 1])
            self.assertAlmostEqual(sketch.Geometry[0].StartPoint.x, 2.0)
            self.assertAlmostEqual(sketch.Geometry[0].StartPoint.y, 3.0)
            self.assertAlmostEqual(sketch.Geometry[1].StartPoint.x, 2.0)
            self.assertAlmostEqual(sketch.Geometry[1].StartPoint.y, 8.0)

            copied = service.registry.call(
                "sketcher.copy_geometry",
                sketch_name=sketch.Name,
                geometry_indices=[0, 1],
                dx=0,
                dy=10,
            )
            self.assertTrue(copied["ok"], copied)
            self.assertEqual(copied["mutation"]["created_geometry_indices"], [5, 6])
            self.assertEqual(copied["transaction"]["result"]["source_geometry_indices"], [0, 1])
            self.assertAlmostEqual(sketch.Geometry[5].StartPoint.x, 2.0)
            self.assertAlmostEqual(sketch.Geometry[5].StartPoint.y, 13.0)
            self.assertAlmostEqual(sketch.Geometry[6].StartPoint.x, 2.0)
            self.assertAlmostEqual(sketch.Geometry[6].StartPoint.y, 18.0)

            array = service.registry.call(
                "sketcher.rectangular_array",
                sketch_name=sketch.Name,
                geometry_indices=[2],
                columns=2,
                rows=2,
                column_dx=10,
                column_dy=0,
                row_dx=0,
                row_dy=10,
            )
            self.assertTrue(array["ok"], array)
            self.assertEqual(array["mutation"]["created_geometry_indices"], [7, 8, 9])
            self.assertEqual(array["transaction"]["result"]["source_geometry_indices"], [2])
            self.assertEqual(len(array["transaction"]["result"]["placements"]), 3)
            self.assertAlmostEqual(sketch.Geometry[7].StartPoint.x, 15.0)
            self.assertAlmostEqual(sketch.Geometry[7].StartPoint.y, 0.0)
            self.assertAlmostEqual(sketch.Geometry[8].StartPoint.x, 5.0)
            self.assertAlmostEqual(sketch.Geometry[8].StartPoint.y, 10.0)
            self.assertAlmostEqual(sketch.Geometry[9].StartPoint.x, 15.0)
            self.assertAlmostEqual(sketch.Geometry[9].StartPoint.y, 10.0)

            mirrored = service.registry.call(
                "sketcher.mirror_geometry",
                sketch_name=sketch.Name,
                geometry_indices=[0],
                axis_point_x=0,
                axis_point_y=0,
                axis_direction_x=0,
                axis_direction_y=1,
            )
            self.assertTrue(mirrored["ok"], mirrored)
            self.assertEqual(mirrored["mutation"]["created_geometry_indices"], [10])
            self.assertEqual(mirrored["transaction"]["result"]["source_geometry_indices"], [0])
            self.assertAlmostEqual(sketch.Geometry[10].StartPoint.x, -2.0)
            self.assertAlmostEqual(sketch.Geometry[10].StartPoint.y, 3.0)
            self.assertAlmostEqual(sketch.Geometry[10].EndPoint.x, -12.0)
            self.assertAlmostEqual(sketch.Geometry[10].EndPoint.y, 3.0)

            offset_line = service.registry.call(
                "sketcher.offset_geometry",
                sketch_name=sketch.Name,
                geometry_indices=[0],
                distance=4,
                side="left",
            )
            self.assertTrue(offset_line["ok"], offset_line)
            self.assertEqual(offset_line["mutation"]["created_geometry_indices"], [11])
            self.assertEqual(offset_line["transaction"]["result"]["source_geometry_indices"], [0])
            self.assertAlmostEqual(sketch.Geometry[11].StartPoint.x, 2.0)
            self.assertAlmostEqual(sketch.Geometry[11].StartPoint.y, 7.0)
            self.assertAlmostEqual(sketch.Geometry[11].EndPoint.x, 12.0)
            self.assertAlmostEqual(sketch.Geometry[11].EndPoint.y, 7.0)

            offset_circle = service.registry.call(
                "sketcher.offset_geometry",
                sketch_name=sketch.Name,
                geometry_indices=[4],
                distance=2,
                side="outward",
            )
            self.assertTrue(offset_circle["ok"], offset_circle)
            self.assertEqual(offset_circle["mutation"]["created_geometry_indices"], [12])
            self.assertAlmostEqual(sketch.Geometry[12].Radius, 7.0)

            tool_calls = [
                ("sketcher.constrain_parallel", {"first_geometry": 0, "second_geometry": 1}),
                ("sketcher.constrain_perpendicular", {"first_geometry": 0, "second_geometry": 2}),
                ("sketcher.constrain_equal", {"first_geometry": 0, "second_geometry": 1}),
                ("sketcher.constrain_distance_x", {"first_geometry": 0, "first_point": "start", "second_geometry": 0, "second_point": "end", "value": 10}),
                ("sketcher.constrain_distance_y", {"first_geometry": 2, "first_point": "start", "second_geometry": 2, "second_point": "end", "value": 5}),
                ("sketcher.constrain_diameter", {"geometry_index": 4, "value": 10}),
                ("sketcher.constrain_tangent", {"first_geometry": 3, "second_geometry": 4}),
                ("sketcher.constrain_point_on_object", {"point_geometry": 0, "point": "start", "object_geometry": 2}),
            ]
            for tool_name, kwargs in tool_calls:
                result = service.registry.call(tool_name, sketch_name=sketch.Name, **kwargs)
                self.assertTrue(result["ok"], (tool_name, result))

            move = service.registry.call(
                "sketcher.move_point",
                sketch_name=sketch.Name,
                geometry_index=3,
                point="end",
                x=32,
                y=5,
            )
            self.assertTrue(move["ok"], move)
            self.assertEqual(move["transaction"]["result"]["point"], "end")
            self.assertEqual(move["mutation"]["modified_geometry_indices"], [3])

            summary = service.sketcher_summary(sketch.Name)
            constraint_types = [item["type"] for item in summary["constraints"]]
            for constraint_type in (
                "Parallel",
                "Perpendicular",
                "Equal",
                "DistanceX",
                "DistanceY",
                "Diameter",
                "Tangent",
                "PointOnObject",
            ):
                self.assertIn(constraint_type, constraint_types)
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_edit_tools_trim_extend_split_and_fillet(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADNativeSketchEditToolsTest")
        try:
            service = VibeCADService()

            extend_sketch = service.registry.call("partdesign.create_sketch", label="Extend Sketch")
            self.assertTrue(extend_sketch["ok"], extend_sketch)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            line = service.registry.call(
                "sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(line["ok"], line)
            extend = service.registry.call(
                "sketcher.extend_geometry",
                sketch_name=sketch.Name,
                geometry_index=0,
                endpoint="end",
                increment=5,
            )
            self.assertTrue(extend["ok"], extend)
            self.assertEqual(extend["mutation"]["modified_geometry_indices"], [0])
            self.assertAlmostEqual(sketch.Geometry[0].EndPoint.x, 15.0)

            split_sketch = service.registry.call(
                "sketcher.create_sketch",
                label="Split Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(split_sketch["ok"], split_sketch)
            split_name = split_sketch["active_sketch"]
            split_line = service.registry.call(
                "sketcher.add_line",
                sketch_name=split_name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(split_line["ok"], split_line)
            split = service.registry.call(
                "sketcher.split_geometry",
                sketch_name=split_name,
                geometry_index=0,
                x=5,
                y=0,
            )
            self.assertTrue(split["ok"], split)
            self.assertGreaterEqual(split["mutation"]["geometry_count"], 2)

            trim_sketch = service.registry.call(
                "sketcher.create_sketch",
                label="Trim Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(trim_sketch["ok"], trim_sketch)
            trim_name = trim_sketch["active_sketch"]
            circle = service.registry.call(
                "sketcher.add_circle",
                sketch_name=trim_name,
                center_x=0,
                center_y=0,
                radius=5,
            )
            self.assertTrue(circle["ok"], circle)
            trim = service.registry.call(
                "sketcher.trim_geometry",
                sketch_name=trim_name,
                geometry_index=0,
                x=5,
                y=0,
            )
            self.assertTrue(trim["ok"], trim)
            self.assertEqual(trim["transaction"]["result"]["geometry_count_before"], 1)
            self.assertLessEqual(trim["mutation"]["geometry_count"], 1)

            fillet_sketch = service.registry.call(
                "sketcher.create_sketch",
                label="Fillet Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(fillet_sketch["ok"], fillet_sketch)
            fillet_name = fillet_sketch["active_sketch"]
            first = service.registry.call(
                "sketcher.add_line",
                sketch_name=fillet_name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            second = service.registry.call(
                "sketcher.add_line",
                sketch_name=fillet_name,
                start_x=10,
                start_y=0,
                end_x=10,
                end_y=10,
            )
            self.assertTrue(first["ok"], first)
            self.assertTrue(second["ok"], second)
            coincident = service.registry.call(
                "sketcher.constrain_coincident",
                sketch_name=fillet_name,
                first_geometry=0,
                first_point="end",
                second_geometry=1,
                second_point="start",
            )
            self.assertTrue(coincident["ok"], coincident)
            fillet = service.registry.call(
                "sketcher.fillet_corner",
                sketch_name=fillet_name,
                first_geometry=0,
                first_point="end",
                radius=2,
                trim=True,
                preserve_corner=True,
            )
            self.assertTrue(fillet["ok"], fillet)
            self.assertGreaterEqual(len(fillet["mutation"]["created_geometry_indices"]), 1)
            fillet_summary = service.sketcher_summary(fillet_name)
            self.assertIn("ArcOfCircle", [item["type"] for item in fillet_summary["geometry"]])
        finally:
            App.closeDocument(doc.Name)

    def test_native_sketcher_external_geometry_tools_add_list_and_remove(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSketchExternalGeometryToolsTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "ReferenceBox")
            box.Length = 10
            box.Width = 8
            box.Height = 4
            doc.recompute()

            sketch_result = service.registry.call(
                "sketcher.create_sketch",
                label="External Reference Sketch",
                support_type="origin_plane",
                plane="XY_Plane",
                open_for_edit=False,
            )
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch_name = sketch_result["active_sketch"]

            references = service.registry.call(
                "sketcher.list_reference_geometry",
                object_name=box.Name,
                max_references=30,
            )
            self.assertTrue(references["ok"], references)
            reference_names = {
                ref["subelement"]
                for obj in references["objects"]
                for ref in obj["references"]
            }
            self.assertIn("Edge1", reference_names)
            self.assertIn("Face1", reference_names)

            add_external = service.registry.call(
                "sketcher.add_external_geometry",
                sketch_name=sketch_name,
                source_object=box.Name,
                subelement="Edge1",
            )
            self.assertTrue(add_external["ok"], add_external)
            self.assertEqual(add_external["transaction"]["result"]["external_geometry_index"], 0)
            self.assertEqual(add_external["transaction"]["result"]["external_geometry_id"], -1)

            external = service.registry.call(
                "sketcher.list_external_geometry",
                sketch_name=sketch_name,
            )
            self.assertTrue(external["ok"], external)
            self.assertEqual(external["external_geometry_count"], 1)
            self.assertEqual(external["external_geometry"][0]["source_object"], box.Name)
            self.assertEqual(external["external_geometry"][0]["subelements"], ["Edge1"])

            remove = service.registry.call(
                "sketcher.remove_external_geometry",
                sketch_name=sketch_name,
                external_geometry_index=0,
            )
            self.assertTrue(remove["ok"], remove)
            self.assertEqual(remove["transaction"]["result"]["deleted_external_geometry_index"], 0)
            external_after = service.registry.call(
                "sketcher.list_external_geometry",
                sketch_name=sketch_name,
            )
            self.assertTrue(external_after["ok"], external_after)
            self.assertEqual(external_after["external_geometry_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_pad_sketch_and_feature_dimension_edit_work_in_place(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignPadEditTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Pad Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call("sketcher.draw_rectangle",
                width=10,
                height=10,
                sketch_name=sketch.Name,
            )
            self.assertTrue(draw_result["ok"], draw_result)
            pad_result = service.registry.call("partdesign.pad_sketch",
                sketch_name=sketch.Name,
                label="Editable Pad",
                length=7,
            )
            self.assertTrue(pad_result["ok"], pad_result)
            self.assertTrue(pad_result["feature_effect"]["ok"], pad_result)
            self.assertGreater(
                pad_result["feature_effect"]["body_shape_delta"]["volume_delta"],
                0.0,
                pad_result,
            )
            self.assertGreater(pad_result["feature_shape"]["faces"], 0, pad_result)
            pad_name = pad_result["transaction"]["result"]["feature"]
            pad = doc.getObject(pad_name)
            self.assertIsNotNone(pad)
            self.assertEqual(pad.TypeId, "PartDesign::Pad")
            self.assertAlmostEqual(float(pad.Length), 7.0)
            edit_result = service.registry.call("partdesign.set_feature_dimensions",
                feature_name=pad.Name,
                length=12,
            )
            self.assertTrue(edit_result["ok"], edit_result)
            self.assertIs(doc.getObject(pad_name), pad)
            self.assertAlmostEqual(float(pad.Length), 12.0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_create_body_allows_separate_component_sketches(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignCreateBodyTest")
        try:
            service = VibeCADService()
            first = service.registry.call("partdesign.create_body", label="Base Component")
            self.assertTrue(first["ok"], first)
            second = service.registry.call("partdesign.create_body", label="Arm Link Component")
            self.assertTrue(second["ok"], second)
            self.assertNotEqual(first["active_body"], second["active_body"])

            sketch_result = service.registry.call(
                "partdesign.create_sketch",
                body_name=second["active_body"],
                label="Arm Link Sketch",
                plane="XZ_Plane",
            )
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch_name = sketch_result["active_sketch"]
            second_body = doc.getObject(second["active_body"])
            self.assertIsNotNone(second_body)
            self.assertIn(doc.getObject(sketch_name), list(getattr(second_body, "Group", []) or []))

            label_targeted_sketch = service.registry.call(
                "partdesign.create_sketch",
                body_name=second["active_body_label"],
                label="Arm Link Label Targeted Sketch",
                plane="XY_Plane",
            )
            self.assertTrue(label_targeted_sketch["ok"], label_targeted_sketch)
            label_targeted_name = label_targeted_sketch["active_sketch"]
            self.assertIn(
                doc.getObject(label_targeted_name),
                list(getattr(second_body, "Group", []) or []),
            )
            self.assertEqual(
                label_targeted_sketch["transaction"]["result"]["body"],
                second["active_body"],
            )

            summary = service.partdesign_summary()
            self.assertEqual(summary["body_count"], 2)
            labels = {body["label"] for body in summary["bodies"]}
            self.assertIn("Base Component", labels)
            self.assertIn("Arm Link Component", labels)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_pad_rejects_open_sketch_with_recoverable_next_actions(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignOpenSketchTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Open Pad Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            line_result = service.registry.call("sketcher.add_line",
                sketch_name=sketch.Name,
                start_x=0,
                start_y=0,
                end_x=10,
                end_y=0,
            )
            self.assertTrue(line_result["ok"], line_result)
            pad_result = service.registry.call("partdesign.pad_sketch",
                sketch_name=sketch.Name,
                label="Should Not Pad",
                length=5,
            )
            self.assertFalse(pad_result["ok"], pad_result)
            self.assertTrue(pad_result["recoverable"], pad_result)
            self.assertFalse(pad_result["profile_status"]["closed_profile"], pad_result)
            self.assertIn("closed profile", pad_result["error"])
            self.assertIn(
                "sketcher.add_line",
                {item["tool"] for item in pad_result["next_actions"]},
            )
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_pocket_sketch_creates_native_subtractive_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignPocketTest")
        try:
            service = VibeCADService()
            base_sketch_result = service.registry.call("partdesign.create_sketch", label="Base Pad Sketch")
            self.assertTrue(base_sketch_result["ok"], base_sketch_result)
            base_sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            base_draw = service.registry.call("sketcher.draw_rectangle",
                width=30,
                height=20,
                sketch_name=base_sketch.Name,
            )
            self.assertTrue(base_draw["ok"], base_draw)
            pad_result = service.registry.call("partdesign.pad_sketch",
                sketch_name=base_sketch.Name,
                label="Pocket Base Pad",
                length=10,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            pocket_sketch_result = service.registry.call("partdesign.create_sketch", label="Pocket Sketch")
            self.assertTrue(pocket_sketch_result["ok"], pocket_sketch_result)
            pocket_sketches = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Label == "Pocket Sketch"
            ]
            self.assertEqual(len(pocket_sketches), 1)
            pocket_sketch = pocket_sketches[0]
            pocket_draw = service.registry.call("sketcher.draw_rectangle",
                width=8,
                height=6,
                sketch_name=pocket_sketch.Name,
            )
            self.assertTrue(pocket_draw["ok"], pocket_draw)
            pocket_result = service.registry.call("partdesign.pocket_sketch",
                sketch_name=pocket_sketch.Name,
                label="Cable Recess Pocket",
                length=3,
                reversed=True,
            )
            self.assertTrue(pocket_result["ok"], pocket_result)
            self.assertTrue(pocket_result["feature_effect"]["ok"], pocket_result)
            self.assertLess(
                pocket_result["feature_effect"]["body_shape_delta"]["volume_delta"],
                0.0,
                pocket_result,
            )
            self.assertGreater(pocket_result["feature_shape"]["faces"], 0, pocket_result)
            pocket_name = pocket_result["transaction"]["result"]["feature"]
            pocket = doc.getObject(pocket_name)
            self.assertIsNotNone(pocket)
            self.assertEqual(pocket.TypeId, "PartDesign::Pocket")
            self.assertAlmostEqual(float(pocket.Length), 3.0)
            body = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"][0]
            self.assertIs(getattr(body, "Tip", None), pocket)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_hole_from_sketch_creates_native_hole_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignHoleTest")
        try:
            service = VibeCADService()
            base_sketch_result = service.registry.call("partdesign.create_sketch", label="Hole Base Sketch")
            self.assertTrue(base_sketch_result["ok"], base_sketch_result)
            base_sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            base_draw = service.registry.call(
                "sketcher.draw_rectangle",
                width=30,
                height=20,
                sketch_name=base_sketch.Name,
            )
            self.assertTrue(base_draw["ok"], base_draw)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=base_sketch.Name,
                label="Hole Base Pad",
                length=10,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            hole_sketch_result = service.registry.call(
                "partdesign.create_sketch",
                label="Bolt Hole Sketch",
            )
            self.assertTrue(hole_sketch_result["ok"], hole_sketch_result)
            hole_sketch = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Label == "Bolt Hole Sketch"
            ][0]
            circle = service.registry.call(
                "sketcher.add_circle",
                sketch_name=hole_sketch.Name,
                center_x=0,
                center_y=0,
                radius=2,
            )
            self.assertTrue(circle["ok"], circle)
            hole_result = service.registry.call(
                "partdesign.hole_from_sketch",
                sketch_name=hole_sketch.Name,
                label="Native Bolt Hole",
                diameter=6,
                depth=10,
                depth_type=0,
                hole_cut_type=1,
                hole_cut_diameter=9,
                hole_cut_depth=3,
                sketch_map_reversed=True,
            )
            self.assertTrue(hole_result["ok"], hole_result)
            self.assertTrue(hole_result["feature_effect"]["ok"], hole_result)
            self.assertLess(
                hole_result["feature_effect"]["body_shape_delta"]["volume_delta"],
                0.0,
                hole_result,
            )
            hole_name = hole_result["transaction"]["result"]["feature"]
            hole = doc.getObject(hole_name)
            self.assertIsNotNone(hole)
            self.assertEqual(hole.TypeId, "PartDesign::Hole")
            self.assertAlmostEqual(float(hole.Diameter), 6.0)
            self.assertIn(str(hole_result["transaction"]["result"]["hole_cut_type"]), {"1", "Counterbore"})
            self.assertAlmostEqual(float(hole.HoleCutDiameter), 9.0)
            body = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"][0]
            self.assertIs(getattr(body, "Tip", None), hole)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_pocket_reports_no_effect_as_recoverable_failure(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignPocketNoEffectTest")
        try:
            service = VibeCADService()
            base_sketch_result = service.registry.call("partdesign.create_sketch", label="Base Pad Sketch")
            self.assertTrue(base_sketch_result["ok"], base_sketch_result)
            base_sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            base_draw = service.registry.call(
                "sketcher.draw_rectangle",
                width=30,
                height=20,
                sketch_name=base_sketch.Name,
            )
            self.assertTrue(base_draw["ok"], base_draw)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=base_sketch.Name,
                label="Pocket Base Pad",
                length=10,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            pocket_sketch_result = service.registry.call("partdesign.create_sketch", label="Pocket Sketch")
            self.assertTrue(pocket_sketch_result["ok"], pocket_sketch_result)
            pocket_sketch = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Label == "Pocket Sketch"
            ][0]
            pocket_draw = service.registry.call(
                "sketcher.draw_rectangle",
                width=8,
                height=6,
                sketch_name=pocket_sketch.Name,
            )
            self.assertTrue(pocket_draw["ok"], pocket_draw)
            pocket_result = service.registry.call(
                "partdesign.pocket_sketch",
                sketch_name=pocket_sketch.Name,
                label="No Effect Pocket",
                length=3,
            )
            self.assertFalse(pocket_result["ok"], pocket_result)
            self.assertTrue(pocket_result["recoverable"], pocket_result)
            self.assertTrue(pocket_result["rolled_back_feature"], pocket_result)
            self.assertIsNone(doc.getObject(pocket_result["active_feature"]))
            self.assertFalse(pocket_result["feature_effect"]["ok"], pocket_result)
            self.assertEqual(
                0.0,
                pocket_result["feature_effect"]["body_shape_delta"]["volume_delta"],
            )
            self.assertIn("did not remove material", pocket_result["error"])
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_linear_pattern_reports_feature_effect(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignLinearPatternEffectTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Pattern Base Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call(
                "sketcher.draw_rectangle",
                width=8,
                height=6,
                sketch_name=sketch.Name,
            )
            self.assertTrue(draw_result["ok"], draw_result)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=sketch.Name,
                label="Pattern Source Pad",
                length=4,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            pattern_result = service.registry.call(
                "partdesign.linear_pattern",
                feature_name=pad_result["active_feature"],
                label="Verified Linear Pattern",
                direction="X_Axis",
                length=18,
                occurrences=2,
            )
            self.assertTrue(pattern_result["ok"], pattern_result)
            self.assertTrue(pattern_result["feature_effect"]["ok"], pattern_result)
            self.assertGreater(pattern_result["body_shape_delta"]["volume_delta"], 0.0, pattern_result)
            self.assertFalse(pattern_result["rolled_back_feature"], pattern_result)
            pattern = doc.getObject(pattern_result["active_feature"])
            self.assertIsNotNone(pattern)
            self.assertEqual(pattern.TypeId, "PartDesign::LinearPattern")
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_fillet_reports_invalid_no_effect_as_recoverable_failure(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignFilletNoEffectTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Fillet Base Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call(
                "sketcher.draw_rectangle",
                width=10,
                height=10,
                sketch_name=sketch.Name,
            )
            self.assertTrue(draw_result["ok"], draw_result)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=sketch.Name,
                label="Fillet Base Pad",
                length=3,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            fillet_result = service.registry.call(
                "partdesign.fillet_feature",
                feature_name=pad_result["active_feature"],
                label="Impossible Fillet",
                radius=1000,
            )
            self.assertFalse(fillet_result["ok"], fillet_result)
            self.assertTrue(fillet_result.get("recoverable"), fillet_result)
            if fillet_result.get("feature_effect") is not None:
                self.assertFalse(fillet_result["feature_effect"]["ok"], fillet_result)
            if fillet_result.get("active_feature"):
                self.assertTrue(fillet_result["rolled_back_feature"], fillet_result)
                self.assertIsNone(doc.getObject(fillet_result["active_feature"]))
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_revolve_sketch_creates_native_revolution_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignRevolutionTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Revolution Profile")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            profile_result = service.registry.call(
                "sketcher.add_polyline",
                sketch_name=sketch.Name,
                points=[[2, 0], [4, 0], [4, 6], [2, 6]],
                closed=True,
            )
            self.assertTrue(profile_result["ok"], profile_result)
            self.assertEqual(profile_result["profile_status"]["degrees_of_freedom"], 0)
            revolve_result = service.registry.call("partdesign.revolve_sketch",
                sketch_name=sketch.Name,
                label="Turned Test Boss",
                angle=180,
                axis="X_Axis",
            )
            self.assertTrue(revolve_result["ok"], revolve_result)
            feature_name = revolve_result["transaction"]["result"]["feature"]
            feature = doc.getObject(feature_name)
            self.assertIsNotNone(feature)
            self.assertEqual(feature.TypeId, "PartDesign::Revolution")
            self.assertAlmostEqual(float(feature.Angle), 180.0)
            self.assertGreater(len(getattr(feature.Shape, "Faces", [])), 0)
            self.assertGreater(float(getattr(feature.Shape, "Volume", 0.0)), 0.0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_revolve_rejects_profile_crossing_in_plane_axis(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignRevolutionPreflightTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Crossing Revolution Profile")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            profile_result = service.registry.call(
                "sketcher.draw_rectangle",
                sketch_name=sketch.Name,
                width=2,
                height=4,
                center_x=3,
                center_y=0,
            )
            self.assertTrue(profile_result["ok"], profile_result)

            revolve_result = service.registry.call(
                "partdesign.revolve_sketch",
                sketch_name=sketch.Name,
                label="Invalid Crossing Revolution",
                axis="X_Axis",
            )

            self.assertFalse(revolve_result["ok"], revolve_result)
            self.assertTrue(revolve_result["recoverable"])
            self.assertTrue(revolve_result["revolution_preflight"]["axis_crosses_profile"])
            self.assertIn("crosses the requested in-plane revolution axis", revolve_result["error"])
            self.assertFalse([
                obj for obj in doc.Objects
                if getattr(obj, "TypeId", "") == "PartDesign::Revolution"
            ])
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_groove_sketch_creates_native_groove_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignGrooveTest")
        try:
            service = VibeCADService()
            base_sketch_result = service.registry.call("partdesign.create_sketch", label="Groove Base Sketch")
            self.assertTrue(base_sketch_result["ok"], base_sketch_result)
            base_sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            base_profile = service.registry.call(
                "sketcher.draw_rectangle",
                sketch_name=base_sketch.Name,
                width=10,
                height=8,
            )
            self.assertTrue(base_profile["ok"], base_profile)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=base_sketch.Name,
                label="Groove Base Pad",
                length=8,
            )
            self.assertTrue(pad_result["ok"], pad_result)

            groove_sketch_result = service.registry.call("partdesign.create_sketch", label="Groove Cut Sketch")
            self.assertTrue(groove_sketch_result["ok"], groove_sketch_result)
            groove_sketches = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Name != base_sketch.Name
            ]
            self.assertEqual(len(groove_sketches), 1)
            groove_sketch = groove_sketches[0]
            groove_profile = service.registry.call(
                "sketcher.add_polyline",
                sketch_name=groove_sketch.Name,
                points=[[-3, 1], [3, 1], [3, 3], [-3, 3]],
                closed=True,
            )
            self.assertTrue(groove_profile["ok"], groove_profile)

            groove_result = service.registry.call(
                "partdesign.groove_sketch",
                sketch_name=groove_sketch.Name,
                label="Native Test Groove",
                angle=360,
                axis="X_Axis",
            )
            self.assertTrue(groove_result["ok"], groove_result)
            self.assertTrue(groove_result["feature_effect"]["ok"], groove_result)
            self.assertLess(groove_result["body_shape_delta"]["volume_delta"], 0.0, groove_result)
            groove = doc.getObject(groove_result["active_feature"])
            self.assertIsNotNone(groove)
            self.assertEqual(groove.TypeId, "PartDesign::Groove")
            self.assertAlmostEqual(float(groove.Angle), 360.0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_datum_and_draft_feature_create_native_draft(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignDraftFeatureTest")
        try:
            service = VibeCADService()
            sketch_result = service.registry.call("partdesign.create_sketch", label="Draft Base Sketch")
            self.assertTrue(sketch_result["ok"], sketch_result)
            sketch = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            draw_result = service.registry.call(
                "sketcher.draw_rectangle",
                sketch_name=sketch.Name,
                width=10,
                height=10,
            )
            self.assertTrue(draw_result["ok"], draw_result)
            pad_result = service.registry.call(
                "partdesign.pad_sketch",
                sketch_name=sketch.Name,
                label="Draft Base Pad",
                length=10,
            )
            self.assertTrue(pad_result["ok"], pad_result)
            pad = doc.getObject(pad_result["active_feature"])
            self.assertIsNotNone(pad)

            plane_result = service.registry.call(
                "partdesign.create_datum_plane",
                label="Draft Neutral Plane",
                support_plane="YZ_Plane",
            )
            self.assertTrue(plane_result["ok"], plane_result)
            line_result = service.registry.call(
                "partdesign.create_datum_line",
                label="Draft Pull Direction",
                support_axis="X_Axis",
            )
            self.assertTrue(line_result["ok"], line_result)

            faces = list(getattr(pad.Shape, "Faces", []) or [])
            z_faces = [
                index for index, face in enumerate(faces)
                if getattr(getattr(face, "Surface", None), "Axis", None) == App.Vector(0, 0, 1)
            ]
            self.assertGreaterEqual(len(z_faces), 1)
            top_index = max(z_faces, key=lambda index: faces[index].CenterOfMass.z)
            draft_result = service.registry.call(
                "partdesign.draft_feature",
                feature_name=pad.Name,
                face_names=[f"Face{top_index + 1}"],
                neutral_plane_name=plane_result["datum"],
                pull_direction_name=line_result["datum"],
                label="Native Test Draft",
                angle=10,
                reversed=True,
            )
            self.assertTrue(draft_result["ok"], draft_result)
            self.assertTrue(draft_result["feature_effect"]["ok"], draft_result)
            draft = doc.getObject(draft_result["active_feature"])
            self.assertIsNotNone(draft)
            self.assertEqual(draft.TypeId, "PartDesign::Draft")
            self.assertAlmostEqual(float(draft.Angle), 10.0)
            self.assertGreater(abs(draft_result["body_shape_delta"]["volume_delta"]), 0.0, draft_result)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_boolean_bodies_creates_native_boolean_cut(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignBooleanBodiesTest")
        try:
            service = VibeCADService()
            tool_body = doc.addObject("PartDesign::Body", "ToolBody")
            tool_box = doc.addObject("PartDesign::AdditiveBox", "ToolBox")
            tool_box.Length = 10
            tool_box.Width = 10
            tool_box.Height = 10
            tool_body.addObject(tool_box)
            tool_body.Tip = tool_box

            target_body = doc.addObject("PartDesign::Body", "TargetBody")
            target_box = doc.addObject("PartDesign::AdditiveBox", "TargetBox")
            target_box.Length = 10
            target_box.Width = 10
            target_box.Height = 10
            target_box.Placement.Base = App.Vector(-5, 0, 0)
            target_body.addObject(target_box)
            target_body.Tip = target_box
            doc.recompute()

            boolean_result = service.registry.call(
                "partdesign.boolean_bodies",
                target_body_name=target_body.Name,
                tool_body_names=[tool_body.Name],
                operation="cut",
                label="Native Boolean Cut",
            )
            self.assertTrue(boolean_result["ok"], boolean_result)
            self.assertTrue(boolean_result["feature_effect"]["ok"], boolean_result)
            self.assertLess(boolean_result["body_shape_delta"]["volume_delta"], 0.0, boolean_result)
            boolean = doc.getObject(boolean_result["active_feature"])
            self.assertIsNotNone(boolean)
            self.assertEqual(boolean.TypeId, "PartDesign::Boolean")
            self.assertIn(str(boolean.Type), {"1", "Cut"})
            self.assertAlmostEqual(float(getattr(boolean.Shape, "Volume", 0.0)), 500.0)
            self.assertIs(getattr(target_body, "Tip", None), boolean)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_loft_profiles_creates_native_additive_loft_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignLoftTest")
        try:
            service = VibeCADService()
            profile_result = service.registry.call("partdesign.create_sketch", label="Loft Profile", plane="XY_Plane")
            self.assertTrue(profile_result["ok"], profile_result)
            profile = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            profile_draw = service.registry.call("sketcher.draw_rectangle",
                width=6,
                height=4,
                sketch_name=profile.Name,
            )
            self.assertTrue(profile_draw["ok"], profile_draw)
            section_result = service.registry.call("partdesign.create_sketch", label="Loft Section", plane="XZ_Plane")
            self.assertTrue(section_result["ok"], section_result)
            section = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Name != profile.Name
            ][0]
            section_draw = service.registry.call("sketcher.draw_rectangle",
                width=3,
                height=2,
                sketch_name=section.Name,
            )
            self.assertTrue(section_draw["ok"], section_draw)

            loft_result = service.registry.call("partdesign.loft_profiles",
                profile_sketch_name=profile.Name,
                section_sketch_names=[section.Name],
                label="Native Additive Loft",
            )
            self.assertTrue(loft_result["ok"], loft_result)
            loft_name = loft_result["transaction"]["result"]["feature"]
            loft = doc.getObject(loft_name)
            self.assertIsNotNone(loft)
            self.assertEqual(loft.TypeId, "PartDesign::AdditiveLoft")
            self.assertEqual(loft.Profile[0], profile)
            self.assertEqual([item[0] for item in loft.Sections], [section])
            self.assertGreater(float(getattr(loft.Shape, "Volume", 0.0)), 0.0)
            body = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"][0]
            self.assertIs(getattr(body, "Tip", None), loft)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_sweep_profile_creates_native_additive_pipe_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignSweepTest")
        try:
            service = VibeCADService()
            profile_result = service.registry.call("partdesign.create_sketch", label="Sweep Profile", plane="XY_Plane")
            self.assertTrue(profile_result["ok"], profile_result)
            profile = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            circle_result = service.registry.call("sketcher.add_circle",
                sketch_name=profile.Name,
                center_x=0,
                center_y=0,
                radius=1,
            )
            self.assertTrue(circle_result["ok"], circle_result)
            spine_result = service.registry.call("partdesign.create_sketch", label="Sweep Spine", plane="XZ_Plane")
            self.assertTrue(spine_result["ok"], spine_result)
            spine = [
                obj for obj in doc.Objects
                if obj.TypeId == "Sketcher::SketchObject" and obj.Name != profile.Name
            ][0]
            line_result = service.registry.call("sketcher.add_line",
                sketch_name=spine.Name,
                start_x=0,
                start_y=0,
                end_x=0,
                end_y=5,
            )
            self.assertTrue(line_result["ok"], line_result)

            sweep_result = service.registry.call("partdesign.sweep_profile",
                profile_sketch_name=profile.Name,
                spine_sketch_name=spine.Name,
                label="Native Additive Pipe",
            )
            self.assertTrue(sweep_result["ok"], sweep_result)
            sweep_name = sweep_result["transaction"]["result"]["feature"]
            sweep = doc.getObject(sweep_name)
            self.assertIsNotNone(sweep)
            self.assertEqual(sweep.TypeId, "PartDesign::AdditivePipe")
            self.assertEqual(sweep.Profile[0], profile)
            self.assertEqual(sweep.Spine[0], spine)
            self.assertGreater(float(getattr(sweep.Shape, "Volume", 0.0)), 0.0)
            body = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"][0]
            self.assertIs(getattr(body, "Tip", None), sweep)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_helix_profile_creates_native_additive_helix_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignHelixTest")
        try:
            service = VibeCADService()
            profile_result = service.registry.call("partdesign.create_sketch", label="Helix Profile")
            self.assertTrue(profile_result["ok"], profile_result)
            profile = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"][0]
            circle_result = service.registry.call(
                "sketcher.add_circle",
                sketch_name=profile.Name,
                center_x=2,
                center_y=0,
                radius=0.5,
            )
            self.assertTrue(circle_result["ok"], circle_result)
            radius_result = service.registry.call(
                "sketcher.constrain_radius",
                sketch_name=profile.Name,
                geometry_index=0,
                value=0.5,
            )
            self.assertTrue(radius_result["ok"], radius_result)
            lock_result = service.registry.call(
                "sketcher.constrain_lock_point",
                sketch_name=profile.Name,
                geometry=0,
                point="center",
                x=2,
                y=0,
            )
            self.assertTrue(lock_result["ok"], lock_result)
            close_result = service.registry.call("sketcher.close_sketch", sketch_name=profile.Name)
            self.assertTrue(close_result["ok"], close_result)

            helix_result = service.registry.call(
                "partdesign.helix_profile",
                profile_sketch_name=profile.Name,
                label="Native Additive Helix",
                mode="additive",
                reference_axis="V_Axis",
                pitch=3,
                height=9,
                turns=3,
                native_mode=0,
            )
            self.assertTrue(helix_result["ok"], helix_result)
            self.assertTrue(helix_result["feature_effect"]["ok"], helix_result)
            self.assertGreater(helix_result["body_shape_delta"]["volume_delta"], 0.0, helix_result)
            helix = doc.getObject(helix_result["active_feature"])
            self.assertIsNotNone(helix)
            self.assertEqual(helix.TypeId, "PartDesign::AdditiveHelix")
            self.assertGreater(float(getattr(helix.Shape, "Volume", 0.0)), 0.0)
            body = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"][0]
            self.assertIs(getattr(body, "Tip", None), helix)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_native_dressup_features_work_on_existing_features(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignEdgeFeaturesTest")
        try:
            body_fillet = doc.addObject("PartDesign::Body", "FilletBody")
            fillet_box = body_fillet.newObject("PartDesign::AdditiveBox", "FilletBaseBox")
            fillet_box.Length = 10
            fillet_box.Width = 8
            fillet_box.Height = 4
            body_fillet.Tip = fillet_box
            body_chamfer = doc.addObject("PartDesign::Body", "ChamferBody")
            chamfer_box = body_chamfer.newObject("PartDesign::AdditiveBox", "ChamferBaseBox")
            chamfer_box.Length = 10
            chamfer_box.Width = 8
            chamfer_box.Height = 4
            body_chamfer.Tip = chamfer_box
            body_thickness = doc.addObject("PartDesign::Body", "ThicknessBody")
            thickness_box = body_thickness.newObject("PartDesign::AdditiveBox", "ThicknessBaseBox")
            thickness_box.Length = 10
            thickness_box.Width = 8
            thickness_box.Height = 4
            body_thickness.Tip = thickness_box
            doc.recompute()

            service = VibeCADService()
            fillet_result = service.registry.call("partdesign.fillet_feature",
                feature_name=fillet_box.Name,
                label="Native Body Fillet",
                radius=0.5,
            )
            self.assertTrue(fillet_result["ok"], fillet_result)
            fillet_name = fillet_result["transaction"]["result"]["feature"]
            fillet = doc.getObject(fillet_name)
            self.assertIsNotNone(fillet)
            self.assertEqual(fillet.TypeId, "PartDesign::Fillet")
            self.assertAlmostEqual(float(fillet.Radius), 0.5)
            self.assertGreater(float(getattr(fillet.Shape, "Volume", 0.0)), 0.0)

            chamfer_result = service.registry.call("partdesign.chamfer_feature",
                feature_name=chamfer_box.Name,
                label="Native Body Chamfer",
                size=0.5,
            )
            self.assertTrue(chamfer_result["ok"], chamfer_result)
            chamfer_name = chamfer_result["transaction"]["result"]["feature"]
            chamfer = doc.getObject(chamfer_name)
            self.assertIsNotNone(chamfer)
            self.assertEqual(chamfer.TypeId, "PartDesign::Chamfer")
            self.assertAlmostEqual(float(chamfer.Size), 0.5)
            self.assertGreater(float(getattr(chamfer.Shape, "Volume", 0.0)), 0.0)

            thickness_result = service.registry.call(
                "partdesign.thickness_feature",
                feature_name=thickness_box.Name,
                label="Native Body Thickness",
                wall_thickness=0.75,
                face_names=["Face1"],
                inward=True,
            )
            self.assertTrue(thickness_result["ok"], thickness_result)
            thickness_name = thickness_result["transaction"]["result"]["feature"]
            thickness = doc.getObject(thickness_name)
            self.assertIsNotNone(thickness)
            self.assertEqual(thickness.TypeId, "PartDesign::Thickness")
            self.assertAlmostEqual(float(thickness.Value), 0.75)
            self.assertEqual(int(thickness.Reversed), 1)
            self.assertGreater(len(getattr(thickness.Shape, "Faces", []) or []), 0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_native_linear_and_polar_patterns_work_on_existing_features(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignPatternFeaturesTest")
        try:
            body_linear = doc.addObject("PartDesign::Body", "LinearBody")
            linear_box = body_linear.newObject("PartDesign::AdditiveBox", "LinearBaseBox")
            linear_box.Length = 10
            linear_box.Width = 8
            linear_box.Height = 4
            body_linear.Tip = linear_box
            body_polar = doc.addObject("PartDesign::Body", "PolarBody")
            polar_box = body_polar.newObject("PartDesign::AdditiveBox", "PolarBaseBox")
            polar_box.Length = 10
            polar_box.Width = 8
            polar_box.Height = 4
            body_polar.Tip = polar_box
            doc.recompute()

            service = VibeCADService()
            linear_result = service.registry.call("partdesign.linear_pattern",
                feature_name=linear_box.Name,
                label="Native Linear Pattern",
                direction="X_Axis",
                length=30,
                occurrences=3,
            )
            self.assertTrue(linear_result["ok"], linear_result)
            linear_name = linear_result["transaction"]["result"]["feature"]
            linear_pattern = doc.getObject(linear_name)
            self.assertIsNotNone(linear_pattern)
            self.assertEqual(linear_pattern.TypeId, "PartDesign::LinearPattern")
            self.assertAlmostEqual(float(linear_pattern.Length), 30.0)
            self.assertEqual(int(linear_pattern.Occurrences), 3)
            self.assertGreater(float(getattr(linear_pattern.Shape, "Volume", 0.0)), 0.0)

            polar_result = service.registry.call("partdesign.polar_pattern",
                feature_name=polar_box.Name,
                label="Native Polar Pattern",
                axis="Z_Axis",
                angle=360,
                occurrences=4,
            )
            self.assertTrue(polar_result["ok"], polar_result)
            polar_name = polar_result["transaction"]["result"]["feature"]
            polar_pattern = doc.getObject(polar_name)
            self.assertIsNotNone(polar_pattern)
            self.assertEqual(polar_pattern.TypeId, "PartDesign::PolarPattern")
            self.assertAlmostEqual(float(polar_pattern.Angle), 360.0)
            self.assertEqual(int(polar_pattern.Occurrences), 4)
            self.assertGreater(float(getattr(polar_pattern.Shape, "Volume", 0.0)), 0.0)
        finally:
            App.closeDocument(doc.Name)

    def test_partdesign_native_mirror_feature_works_on_existing_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartDesignMirrorFeatureTest")
        try:
            body = doc.addObject("PartDesign::Body", "MirrorBody")
            box = body.newObject("PartDesign::AdditiveBox", "MirrorBaseBox")
            box.Length = 10
            box.Width = 8
            box.Height = 4
            body.Tip = box
            doc.recompute()

            service = VibeCADService()
            mirror_result = service.registry.call("partdesign.mirror_feature",
                feature_name=box.Name,
                label="Native Mirrored Feature",
                mirror_plane="YZ_Plane",
            )
            self.assertTrue(mirror_result["ok"], mirror_result)
            mirror_name = mirror_result["transaction"]["result"]["feature"]
            mirrored = doc.getObject(mirror_name)
            self.assertIsNotNone(mirrored)
            self.assertEqual(mirrored.TypeId, "PartDesign::Mirrored")
            self.assertEqual(mirror_result["transaction"]["result"]["mirror_plane"], "YZ_Plane")
            self.assertGreater(float(getattr(mirrored.Shape, "Volume", 0.0)), 0.0)
            self.assertIs(getattr(body, "Tip", None), mirrored)
        finally:
            App.closeDocument(doc.Name)

    def test_techdraw_summary_reads_real_page_template_and_view(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTechDrawSummaryTest")
        try:
            page = doc.addObject("TechDraw::DrawPage", "PageForSummary")
            page.Label = "Readable Page"
            template = doc.addObject("TechDraw::DrawSVGTemplate", "TemplateForSummary")
            template.Label = "Readable Template"
            page.Template = template
            box = doc.addObject("Part::Box", "BoxForView")
            view = doc.addObject("TechDraw::DrawViewPart", "ViewForSummary")
            view.Label = "Readable View"
            view.Source = [box]
            page.addView(view)
            doc.recompute()
            service = VibeCADService()
            summary = service.techdraw_summary(page.Name)
            self.assertEqual(summary["page_count"], 1)
            self.assertEqual(summary["selected"]["name"], page.Name)
            self.assertEqual(summary["selected"]["label"], "Readable Page")
            self.assertEqual(summary["selected"]["template"]["name"], template.Name)
            self.assertEqual(summary["selected"]["view_count"], 1)
            self.assertEqual(summary["selected"]["views"][0]["name"], view.Name)
            self.assertEqual(summary["selected"]["views"][0]["source_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_create_techdraw_page_and_add_view_apply_directly_for_provider_loop(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTechDrawDirectTest")
        try:
            box = doc.addObject("Part::Box", "BoxForDirectDrawing")
            box.Label = "Direct Drawing Source"
            doc.recompute()
            service = VibeCADService()
            page_result = service.registry.call("techdraw.create_page", label="AI Direct Drawing Page", with_template=True)
            self.assertTrue(page_result["ok"], page_result)
            page = next(
                obj for obj in doc.Objects
                if obj.isDerivedFrom("TechDraw::DrawPage")
            )
            self.assertEqual(page.Label, "AI Direct Drawing Page")
            self.assertIsNotNone(page.Template)

            view_result = service.registry.call(
                "techdraw.add_view",
                source_name="Direct Drawing Source",
                page_name="AI Direct Drawing Page",
                label="AI Direct Box View",
                x=80.0,
                y=120.0,
                scale=0.5,
            )
            self.assertTrue(view_result["ok"], view_result)
            views = list(getattr(page, "Views", []) or [])
            self.assertEqual(len(views), 1)
            view = views[0]
            self.assertEqual(view.TypeId, "TechDraw::DrawViewPart")
            self.assertEqual(view.Label, "AI Direct Box View")
            self.assertEqual(list(view.Source), [box])
            self.assertAlmostEqual(float(view.Scale), 0.5)
            summary = service.techdraw_summary(page.Name)
            self.assertEqual(summary["selected"]["view_count"], 1)
            self.assertEqual(summary["selected"]["views"][0]["source_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_fem_summary_reads_real_analysis(self):
        import FreeCAD as App
        import ObjectsFem

        doc = App.newDocument("VibeCADFemSummaryTest")
        try:
            analysis = ObjectsFem.makeAnalysis(doc, "AnalysisForSummary")
            analysis.Label = "Readable Analysis"
            doc.recompute()
            service = VibeCADService()
            summary = service.fem_summary(analysis.Name)
            self.assertEqual(summary["analysis_count"], 1)
            self.assertEqual(summary["selected"]["name"], analysis.Name)
            self.assertEqual(summary["selected"]["label"], "Readable Analysis")
            self.assertEqual(summary["selected"]["member_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_cam_summary_reads_real_job(self):
        import FreeCAD as App
        import Path.Main.Job as PathJob

        doc = App.newDocument("VibeCADCamSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForCam")
            job = PathJob.Create("JobForSummary", [box], None)
            job.Label = "Readable CAM Job"
            doc.recompute()
            service = VibeCADService()
            summary = service.cam_summary(job.Name)
            self.assertEqual(summary["job_count"], 1)
            self.assertEqual(summary["selected"]["name"], job.Name)
            self.assertEqual(summary["selected"]["label"], "Readable CAM Job")
            self.assertEqual(summary["selected"]["operations"]["object_count"], 0)
            self.assertGreaterEqual(summary["selected"]["tools"]["object_count"], 1)
            self.assertEqual(summary["selected"]["model"]["object_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_bim_summary_reads_real_building_part(self):
        import Arch
        import FreeCAD as App

        doc = App.newDocument("VibeCADBimSummaryTest")
        try:
            obj = Arch.makeBuildingPart(name="Readable BIM Part")
            obj.IfcType = "Building Element Part"
            doc.recompute()
            service = VibeCADService()
            summary = service.bim_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable BIM Part")
            self.assertEqual(summary["objects"][0]["ifc_type"], "Building Element Part")
            self.assertEqual(summary["ifc_type_counts"]["Building Element Part"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_assembly_summary_reads_real_assembly(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADAssemblySummaryTest")
        try:
            assembly = doc.addObject("Assembly::AssemblyObject", "AssemblyForSummary")
            assembly.Label = "Readable Assembly"
            assembly.Type = "Assembly"
            joint_group = assembly.newObject("Assembly::JointGroup", "Joints")
            box = assembly.newObject("Part::Box", "BoxInAssembly")
            box.Label = "Assembly Component"
            doc.recompute()
            service = VibeCADService()
            summary = service.assembly_summary()
            self.assertEqual(summary["assembly_count"], 1)
            item = summary["assemblies"][0]
            self.assertEqual(item["name"], assembly.Name)
            self.assertEqual(item["label"], "Readable Assembly")
            self.assertEqual(item["joint_groups"], 1)
            self.assertEqual(item["joints"], 0)
            self.assertEqual(item["components"], 1)
            child_names = {child["name"] for child in item["children"]}
            self.assertIn(joint_group.Name, child_names)
            self.assertIn(box.Name, child_names)
            component_names = {child["name"] for child in item["component_children"]}
            self.assertEqual(component_names, {box.Name})
        finally:
            App.closeDocument(doc.Name)

    def test_add_assembly_component_adds_existing_object_incrementally(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADAssemblyAddComponentTest")
        try:
            base = doc.addObject("Part::Box", "BasePlate")
            base.Label = "Base Plate"
            arm = doc.addObject("Part::Box", "ArmLink")
            arm.Label = "Arm Link"
            doc.recompute()
            service = VibeCADService()
            create_result = service.registry.call("assembly.create_assembly", label="Incremental Assembly")
            self.assertTrue(create_result["ok"], create_result)
            self.assertEqual(create_result["assembly_label"], "Incremental Assembly")
            self.assertEqual(create_result["assembly_summary"]["assembly_count"], 1)
            summary = service.assembly_summary()
            self.assertEqual(summary["assemblies"][0]["components"], 0)

            first = service.registry.call(
                "assembly.add_component",
                assembly_name="Incremental Assembly",
                component_name="Base Plate",
            )
            self.assertTrue(first["ok"], first)
            self.assertEqual(first["transaction"]["result"]["components"], 1)
            self.assertEqual(first["component_label"], "Base Plate")
            self.assertEqual(first["components"], 1)
            self.assertEqual(first["assembly_summary"]["assemblies"][0]["components"], 1)
            second = service.registry.call(
                "assembly.add_component",
                assembly_name="Incremental Assembly",
                component_name=arm.Name,
            )
            self.assertTrue(second["ok"], second)
            self.assertEqual(second["transaction"]["result"]["components"], 2)
            self.assertEqual(second["component_label"], "Arm Link")
            self.assertEqual(second["components"], 2)
            duplicate = service.registry.call(
                "assembly.add_component",
                assembly_name="Incremental Assembly",
                component_name="Base Plate",
            )
            self.assertTrue(duplicate["ok"], duplicate)
            self.assertTrue(duplicate["transaction"]["result"]["already_present"])
            self.assertTrue(duplicate["already_present"])
            self.assertEqual(duplicate["transaction"]["result"]["components"], 2)

            assembly = service.assembly_summary()["assemblies"][0]
            self.assertEqual(assembly["components"], 2)
            labels = {child["label"] for child in assembly["children"]}
            self.assertIn("Base Plate", labels)
            self.assertIn("Arm Link", labels)
        finally:
            App.closeDocument(doc.Name)

    def test_set_assembly_component_placement_positions_existing_component(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADAssemblyPlacementTest")
        try:
            arm = doc.addObject("Part::Box", "ArmLink")
            arm.Label = "Arm Link"
            doc.recompute()
            service = VibeCADService()
            create_result = service.registry.call("assembly.create_assembly", label="Positioned Assembly")
            self.assertTrue(create_result["ok"], create_result)
            add_result = service.registry.call(
                "assembly.add_component",
                assembly_name="Positioned Assembly",
                component_name=arm.Name,
            )
            self.assertTrue(add_result["ok"], add_result)

            placement_result = service.registry.call(
                "assembly.set_component_placement",
                assembly_name="Positioned Assembly",
                component_name="Arm Link",
                x=42,
                y=-8,
                z=12,
                yaw_degrees=30,
                pitch_degrees=0,
                roll_degrees=90,
            )
            self.assertTrue(placement_result["ok"], placement_result)
            self.assertEqual(placement_result["component"], arm.Name)
            self.assertAlmostEqual(float(arm.Placement.Base.x), 42.0)
            self.assertAlmostEqual(float(arm.Placement.Base.y), -8.0)
            self.assertAlmostEqual(float(arm.Placement.Base.z), 12.0)
            self.assertEqual(placement_result["placement"], {"x": 42.0, "y": -8.0, "z": 12.0})
            self.assertEqual(placement_result["assembly_summary"]["assemblies"][0]["components"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_inspection_summary_reads_real_inspection_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADInspectionSummaryTest")
        try:
            actual = doc.addObject("Part::Box", "ActualBox")
            nominal = doc.addObject("Part::Box", "NominalBox")
            group = doc.addObject("Inspection::Group", "Inspection")
            feature = group.newObject("Inspection::Feature", "BoxInspect")
            feature.Label = "Readable Inspection"
            feature.Actual = actual
            feature.Nominals = [nominal]
            feature.SearchRadius = 0.25
            feature.Thickness = 0.1
            doc.recompute()
            service = VibeCADService()
            summary = service.inspection_summary()
            self.assertEqual(summary["group_count"], 1)
            self.assertEqual(summary["feature_count"], 1)
            self.assertGreaterEqual(summary["candidate_count"], 2)
            item = summary["features"][0]
            self.assertEqual(item["name"], feature.Name)
            self.assertEqual(item["label"], "Readable Inspection")
            self.assertEqual(item["actual"]["name"], actual.Name)
            self.assertEqual(item["nominal_count"], 1)
            self.assertEqual(item["nominals"][0]["name"], nominal.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_openscad_summary_reads_relevant_objects(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADOpenSCADSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForOpenSCAD")
            box.Label = "OpenSCAD Candidate Box"
            doc.recompute()
            service = VibeCADService()
            summary = service.openscad_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["label"], "OpenSCAD Candidate Box")
            self.assertEqual(summary["objects"][0]["type"], "Part::Box")
            self.assertIn("openscad_executable_configured", summary)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_summary_reads_real_surface_feature(self):
        import FreeCAD as App
        import Surface  # noqa: F401

        doc = App.newDocument("VibeCADSurfaceSummaryTest")
        try:
            feature = doc.addObject("Surface::Filling", "SurfaceForSummary")
            feature.Label = "Readable Surface"
            service = VibeCADService()
            summary = service.surface_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], feature.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Surface")
            self.assertEqual(summary["objects"][0]["type"], "Surface::Filling")
            self.assertIn("Surface::Filling", summary["feature_types"])
        finally:
            App.closeDocument(doc.Name)

    def test_reverseengineering_summary_reads_candidates_and_outputs(self):
        import FreeCAD as App
        import Points

        doc = App.newDocument("VibeCADReenSummaryTest")
        try:
            pts = Points.Points()
            pts.addPoints([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, -1, 0)])
            cloud = doc.addObject("Points::Feature", "CloudForReen")
            cloud.Points = pts
            spline = doc.addObject("Part::Spline", "SplineForReen")
            spline.Label = "Existing Fit"
            service = VibeCADService()
            summary = service.reverseengineering_summary()
            self.assertEqual(summary["candidate_count"], 1)
            self.assertEqual(summary["candidates"][0]["name"], cloud.Name)
            self.assertEqual(summary["reconstruction_count"], 1)
            self.assertEqual(summary["reconstructions"][0]["name"], spline.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_robot_summary_reads_real_trajectory(self):
        import FreeCAD as App
        import Robot

        doc = App.newDocument("VibeCADRobotSummaryTest")
        try:
            robot = doc.addObject("Robot::RobotObject", "RobotForSummary")
            robot.Label = "Readable Robot"
            trajectory = doc.addObject("Robot::TrajectoryObject", "TrajectoryForSummary")
            trajectory.Label = "Readable Trajectory"
            traj = trajectory.Trajectory
            traj.insertWaypoints(
                Robot.Waypoint(
                    App.Placement(App.Vector(1, 2, 3), App.Rotation(App.Vector(1, 0, 0), 0)),
                    "LIN",
                    "Start",
                )
            )
            trajectory.Trajectory = traj
            service = VibeCADService()
            summary = service.robot_summary()
            self.assertEqual(summary["robot_count"], 1)
            self.assertEqual(summary["robots"][0]["label"], "Readable Robot")
            self.assertEqual(summary["trajectory_count"], 1)
            self.assertEqual(summary["trajectories"][0]["waypoint_count"], 1)
            self.assertEqual(summary["trajectories"][0]["waypoints"][0]["name"], "Start")
        finally:
            App.closeDocument(doc.Name)

    def test_meshpart_summary_reads_part_candidates_and_meshes(self):
        import FreeCAD as App
        import Mesh

        doc = App.newDocument("VibeCADMeshPartSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMeshPart")
            mesh = doc.addObject("Mesh::Feature", "MeshForMeshPart")
            mesh.Mesh = Mesh.createBox(1, 1, 1)
            doc.recompute()
            service = VibeCADService()
            summary = service.meshpart_summary()
            self.assertEqual(summary["part_candidate_count"], 1)
            self.assertEqual(summary["part_candidates"][0]["name"], box.Name)
            self.assertEqual(summary["mesh_count"], 1)
            self.assertEqual(summary["meshes"][0]["name"], mesh.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_workbench_command_summary_uses_tool_pack_prefixes(self):
        service = VibeCADService()
        summary = service.workbench_command_summary("PartWorkbench")
        self.assertEqual(summary["active_workbench"], "PartWorkbench")
        self.assertEqual(summary["command_prefixes"], ["Part_"])
        self.assertIn("commands", summary)
        self.assertIn("command_limit", summary)
        self.assertIn("commands_truncated", summary)
        self.assertIn("commands_omitted", summary)
        self.assertLessEqual(len(summary["commands"]), summary["command_limit"])

    def test_workbench_object_templates_are_exposed(self):
        service = VibeCADService()
        summary = service.workbench_object_templates("PartWorkbench")
        self.assertIn({"name": "box", "object_type": "Part::Box"}, summary["templates"])

    def test_workbench_object_summary_filters_by_pack(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADObjectSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForSummary")
            group = doc.addObject("App::DocumentObjectGroup", "GroupForSummary")
            doc.recompute()
            service = VibeCADService()
            part_summary = service.workbench_object_summary("PartWorkbench")
            sketcher_summary = service.workbench_object_summary("SketcherWorkbench")
            self.assertIn(box.Name, [item["name"] for item in part_summary["objects"]])
            self.assertNotIn(group.Name, [item["name"] for item in part_summary["objects"]])
            self.assertEqual(sketcher_summary["objects"], [])
        finally:
            App.closeDocument(doc.Name)

    def test_large_document_summaries_are_bounded_with_truncation_metadata(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADLargeSummaryTest")
        try:
            try:
                import FreeCADGui as Gui

                Gui.activateWorkbench("PartWorkbench")
            except Exception:
                pass
            for index in range(55):
                obj = doc.addObject("Part::Box", f"LargeSummaryBox{index}")
                obj.Label = f"Large Summary Box {index}"
            doc.recompute()
            service = VibeCADService()

            document = service.document_summary()
            self.assertEqual(document["object_count"], 55)
            self.assertEqual(len(document["objects"]), document["object_limit"])
            self.assertTrue(document["objects_truncated"])
            self.assertEqual(
                document["objects_omitted"],
                document["object_count"] - len(document["objects"]),
            )

            workbench = service.workbench_object_summary("PartWorkbench")
            self.assertEqual(workbench["object_count"], 55)
            self.assertEqual(len(workbench["objects"]), workbench["object_limit"])
            self.assertTrue(workbench["objects_truncated"])
            self.assertEqual(
                workbench["objects_omitted"],
                workbench["object_count"] - len(workbench["objects"]),
            )
            context = service.context_summary()
            self.assertLess(
                len(context["document"]["objects"]),
                context["document"]["object_count"],
            )
            self.assertEqual(
                context["document"]["objects_omitted"],
                context["document"]["object_count"] - len(context["document"]["objects"]),
            )
            if context.get("workbench"):
                self.assertLess(
                    len(context["workbench_objects"]["objects"]),
                    context["workbench_objects"]["object_count"],
                )
            else:
                self.assertEqual(context["workbench_objects"]["object_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_object_property_summary_reads_real_object(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADObjectPropertyTest")
        try:
            box = doc.addObject("Part::Box", "BoxForProperties")
            box.Label = "Readable Box"
            service = VibeCADService()
            summary = service.object_property_summary(box.Name)
            self.assertTrue(summary["found"])
            self.assertEqual(summary["object"]["label"], "Readable Box")
            self.assertIn("Label", summary["properties"])
        finally:
            App.closeDocument(doc.Name)

    def test_run_prompt_rejects_empty_prompt(self):
        with self.assertRaises(ValueError):
            run_prompt(" ", service=VibeCADService(), prefer_online=False)

    def test_activate_workbench_reports_failure_without_gui(self):
        result = VibeCADService().activate_workbench("NoSuchWorkbench")
        self.assertIn("activated", result)
        self.assertIn("requested", result)

    def test_missing_action_apply_is_reported(self):
        result = VibeCADService().apply_action("missing")
        self.assertEqual(result["status"], "missing")

    def test_approval_queue_apply_runs_handler(self):
        queue = ApprovalQueue()
        proposal = queue.propose(
            "test",
            "test proposal",
            "safe_write",
            None,
            lambda: {"changed": True},
        )
        result = queue.apply(proposal["id"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["result"]["result"]["changed"], True)
        self.assertTrue(result["result"]["verification"]["ok"])

    def test_workbench_tool_packs_cover_integrated_workbenches(self):
        expected = {
            "AssemblyWorkbench",
            "BIMWorkbench",
            "CAMWorkbench",
            "DraftWorkbench",
            "FemWorkbench",
            "InspectionWorkbench",
            "MaterialWorkbench",
            "MeshWorkbench",
            "MeshPartWorkbench",
            "NoneWorkbench",
            "OpenSCADWorkbench",
            "PartDesignWorkbench",
            "PartWorkbench",
            "PointsWorkbench",
            "ReverseEngineeringWorkbench",
            "RobotWorkbench",
            "SketcherWorkbench",
            "SpreadsheetWorkbench",
            "SurfaceWorkbench",
            "TechDrawWorkbench",
            "TestWorkbench",
        }
        self.assertEqual(expected, set(WORKBENCH_TOOL_PACKS))
        self.assertEqual(get_tool_pack("PartWorkbench").domain, "boundary-representation solids")
        for pack in WORKBENCH_TOOL_PACKS.values():
            self.assertGreater(len(pack.object_templates), 0, pack.workbench)

    def test_runtime_workbenches_have_tool_packs(self):
        if not _gui_workbench_api_available():
            self.skipTest("FreeCAD GUI workbench API unavailable")
        try:
            import FreeCADGui as Gui
        except Exception:
            self.skipTest("FreeCADGui unavailable")
        runtime_workbenches = set(Gui.listWorkbenches())
        missing = runtime_workbenches.difference(WORKBENCH_TOOL_PACKS)
        self.assertEqual(set(), missing)

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

        class FakeService:
            _last_view_screenshot = None

            def _screenshot_visual_observation(self, path):
                return {"available": True, "mostly_blank": False}

        original_app = sys.modules.get("FreeCAD")
        original_gui = sys.modules.get("FreeCADGui")
        sys.modules["FreeCAD"] = fake_app
        sys.modules["FreeCADGui"] = fake_gui
        service = FakeService()
        try:
            result = module.run(service)
            self.assertTrue(result["ok"])
            self.assertTrue(result["captured"])
            self.assertGreater(result["file_size"], 1000)
            self.assertEqual(result["format"], "png")
            self.assertEqual(result["background"], "White")
            self.assertEqual(result["workbench"], "PartDesignWorkbench")
            self.assertEqual(result["document"], "VibeCADTestDoc")
            self.assertNotIn("exists", result)
            self.assertNotIn("size_bytes", result)
            self.assertEqual(service._last_view_screenshot, result)
        finally:
            path = service._last_view_screenshot.get("path") if service._last_view_screenshot else None
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

    def test_agents_provider_fails_cleanly_when_sdk_missing(self):
        try:
            import agents  # noqa: F401
        except Exception:
            with self.assertRaises(ProviderUnavailable):
                OpenAIAgentsProvider().run("hello", {})


if __name__ == "__main__":
    unittest.main()
