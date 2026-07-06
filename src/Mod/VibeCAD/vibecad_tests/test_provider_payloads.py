# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import inspect
import json
from pathlib import Path
import tempfile

import VibeCADProject
from VibeCADCore import (
    VibeCADService,
)
from VibeCADPreferences import (
    DEFAULT_MODEL,
)
from VibeCADProvider import (
    OPENAI_REQUEST_DUMP_DIR_ENV,
    _build_provider_function_tools,
    _model_visible_context,
    _openai_request_dump_dir,
    _provider_tool_request_schema,
    _write_openai_request_dump,
)
from VibeCADSession import (
    _execution_contract_for_context,
    _refresh_provider_context,
    make_provider_tool_runner,
    provider_tool_scope_for_context,
    provider_safe_tool_schemas,
    run_prompt,
)
from VibeCADWorkbenchTools import WORKBENCH_TOOL_PACKS

from vibecad_tests.support import (
    SettingsSnapshotTestCase,
    _attach_temp_project_store,
)


class TestVibeCADProviderPayloads(SettingsSnapshotTestCase):
    def test_run_prompt_includes_provider_tool_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = VibeCADService()
            original = _attach_temp_project_store(service, Path(tmp))
            try:
                response = run_prompt("hello", service=service, prefer_online=False)
                self.assertEqual(response.provider, "OfflineProvider")
                self.assertNotIn("available_tools", response.context)
                self.assertIn("provider_tool_schemas", response.context)
                provider_tool_names = {
                    schema["name"]
                    for schema in response.context["provider_tool_schemas"]
                    if isinstance(schema, dict)
                }
                self.assertIn("core.get_active_document", provider_tool_names)
                self.assertIn("core.enter_workspace", provider_tool_names)
                self.assertNotIn("core.activate_workbench", provider_tool_names)
                self.assertNotIn("partdesign.create_body", provider_tool_names)
                self.assertNotIn("sketcher.add_geometry", provider_tool_names)
                self.assertIn("workbench_tool_pack", response.context)
                self.assertIn("workbench_commands", response.context)
                self.assertIn("workbench_object_templates", response.context)
                self.assertIn("workbench_objects", response.context)
                self.assertIn("provider_tool_scope", response.context)
                self.assertEqual(
                    response.context["provider_tool_scope"]["stage"], "workspace_planner"
                )
                self.assertIn("active_tool_count", response.context["provider_tool_scope"])
                self.assertIn("active_tool_names", response.context["provider_tool_scope"])
                self.assertNotIn("omitted_tool_names", response.context["provider_tool_scope"])
                self.assertEqual(response.context["vibecad_workspace"]["mode"], "planner")
                self.assertEqual(
                    response.context["vibecad_workspace"]["available_workspaces"],
                    sorted(WORKBENCH_TOOL_PACKS),
                )
                visible = _model_visible_context(response.context)
                self.assertIn("provider_tool_scope", visible)
                self.assertNotIn("provider_tool_schemas", visible)
                self.assertNotIn("provider_tool_surface", visible)
                self.assertNotIn("active_tool_names", visible["provider_tool_scope"])
                self.assertIn("active_tool_name_count", visible["provider_tool_scope"])
                self.assertNotIn("omitted_tool_names", visible["provider_tool_scope"])
                self.assertNotIn("available_tools", response.context)
                self.assertIn("provider_tool_surface", response.context)
                self.assertIn("view_screenshot", response.context)
                self.assertIn("task_panel", response.context)
                self.assertIn("report_view_errors", response.context)
            finally:
                VibeCADProject._active_document_info = original

    def test_modify_existing_request_allows_new_body_creation(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADModifyAllowsBodyTest")
        with tempfile.TemporaryDirectory() as tmp:
            service = VibeCADService()
            original = _attach_temp_project_store(service, Path(tmp), "Modify Allows Body")
            try:
                created = service.registry.call("partdesign.create_body", label="Existing Frame")
                self.assertTrue(created["ok"], created)
                runner = make_provider_tool_runner(
                    service,
                    workbench="PartDesignWorkbench",
                )
                result = runner("partdesign.create_body", '{"label": "Housing Body"}')
                self.assertTrue(result["ok"], result)
            finally:
                VibeCADProject._active_document_info = original
                App.closeDocument(doc.Name)

    def test_modify_existing_prompt_keeps_body_and_delete_tools_visible(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADModifySurfaceTest")
        with tempfile.TemporaryDirectory() as tmp:
            service = VibeCADService()
            original = _attach_temp_project_store(service, Path(tmp), "Modify Surface")
            try:
                created = service.registry.call("partdesign.create_body", label="Existing Frame")
                self.assertTrue(created["ok"], created)

                context = _refresh_provider_context(
                    service,
                    prompt="fix this model",
                    entered_workspace="PartDesignWorkbench",
                )
                names = {
                    schema["name"]
                    for schema in context["provider_tool_schemas"]
                    if isinstance(schema, dict)
                }

                self.assertNotIn("vibecad_request", context)
                self.assertIn("partdesign.create_body", names)
                self.assertIn("core.delete_object", names)
                self.assertIn("partdesign.create_sketch", names)
                self.assertIn("partdesign.extrude", names)
                scope = context["provider_tool_surface"]["scope"]
                self.assertNotIn("request_filter", scope)
            finally:
                VibeCADProject._active_document_info = original
                App.closeDocument(doc.Name)

    def test_document_management_tools_remain_blocked_for_provider(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDocMgmtBlockedTest")
        with tempfile.TemporaryDirectory() as tmp:
            service = VibeCADService()
            original = _attach_temp_project_store(service, Path(tmp), "Doc Mgmt Blocked")
            try:
                runner = make_provider_tool_runner(
                    service,
                    workbench="PartDesignWorkbench",
                )
                result = runner("core.create_new_document", '{"name": "Sneaky"}')
                self.assertFalse(result["ok"])
                self.assertIn("not available to the autonomous CAD loop", result["error"])
            finally:
                VibeCADProject._active_document_info = original
                App.closeDocument(doc.Name)

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
            "partdesign.extrude",
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
                "partdesign_extrude",
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

        self.assertEqual(scope.stage, "workbench_pack")
        self.assertEqual(len(request_tools), len(scoped))
        self.assertLessEqual(len(request_tools), len(full))
        self.assertIn("partdesign_create_body", function_names)
        self.assertIn("partdesign_create_sketch", function_names)
        self.assertIn("partdesign_extrude", function_names)
        self.assertNotIn("sketcher_create_sketch", function_names)
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
                "available_tools": [{"name": "part.set_placement"}],
                "available_tools_workbench": "PartWorkbench",
                "provider_tool_schemas": [{"name": "part.set_placement"}],
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
        self.assertIn("native PartDesign features built from constrained sketches", gates)

    def test_openai_request_dump_writes_full_provider_payload(self):
        old_dump_dir = os.environ.get(OPENAI_REQUEST_DUMP_DIR_ENV)
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ[OPENAI_REQUEST_DUMP_DIR_ENV] = directory
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
                os.environ.pop(OPENAI_REQUEST_DUMP_DIR_ENV, None)
            else:
                os.environ[OPENAI_REQUEST_DUMP_DIR_ENV] = old_dump_dir

    def test_openai_request_dump_defaults_to_durable_user_storage(self):
        old_dump_dir = os.environ.get(OPENAI_REQUEST_DUMP_DIR_ENV)
        old_home = os.environ.get("VIBECAD_HOME")
        try:
            os.environ.pop(OPENAI_REQUEST_DUMP_DIR_ENV, None)
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
                home = Path(directory) / "vibecad-home"
                os.environ["VIBECAD_HOME"] = str(home)
                dump_dir = _openai_request_dump_dir()
                self.assertEqual(
                    dump_dir,
                    home / "debug" / "openai-request-dumps",
                )
                path = _write_openai_request_dump(
                    {"schema": "vibecad-openai-agents-request-v1", "model": DEFAULT_MODEL}
                )
                self.assertIsNotNone(path)
                self.assertTrue(str(path).startswith(str(home)))
                self.assertTrue((home / "debug" / "openai-request-dumps" / "latest-openai-request.json").is_file())
        finally:
            if old_dump_dir is None:
                os.environ.pop(OPENAI_REQUEST_DUMP_DIR_ENV, None)
            else:
                os.environ[OPENAI_REQUEST_DUMP_DIR_ENV] = old_dump_dir
            if old_home is None:
                os.environ.pop("VIBECAD_HOME", None)
            else:
                os.environ["VIBECAD_HOME"] = old_home
