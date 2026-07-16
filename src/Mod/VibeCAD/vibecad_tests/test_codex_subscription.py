# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused contracts for the ChatGPT subscription transport."""

from __future__ import annotations

import base64
from pathlib import Path
import sys

import pytest

import VibeCADCodex as codex
import VibeCADPreferences as preferences
import VibeCADProvider as provider
import VibeCADSession as session


def _scripted_context() -> dict:
    schema = {
        "name": "vibescript.inspect_model",
        "description": "Inspect one VibeScript model.",
        "parameters": {
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "Exact model identifier.",
                }
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    }
    return {
        "provider_tool_schemas": [schema],
        "provider_tool_surface": {
            "kind": "scripted",
            "fixed": True,
            "engine": "vibescript",
            "workbench": "PartDesignWorkbench",
            "tool_names": ["vibescript.inspect_model"],
        },
    }


def test_codex_dynamic_tools_require_a_fixed_scripted_surface() -> None:
    context = _scripted_context()
    context.pop("provider_tool_surface")
    with pytest.raises(provider.ProviderUnavailable, match="fixed VibeCAD scripted"):
        provider._codex_dynamic_tool_surface(context)


def test_fixed_scripted_surface_is_independent_of_workbench() -> None:
    schemas = _scripted_context()["provider_tool_schemas"]
    surface = session._fixed_scripted_surface("FemWorkbench", schemas)
    assert surface == {
        "kind": "scripted",
        "fixed": True,
        "engine": "vibescript",
        "workbench": "FemWorkbench",
        "tool_names": ["vibescript.inspect_model"],
    }


def test_fixed_scripted_surface_accepts_approved_vibescript_adjuncts() -> None:
    schemas = [{"name": name} for name in sorted(session.VIBESCRIPT_PROVIDER_TOOLS)]
    surface = session._fixed_scripted_surface("PartDesignWorkbench", schemas)
    assert surface is not None
    assert surface["engine"] == "vibescript"
    assert surface["tool_names"] == [schema["name"] for schema in schemas]


def test_fixed_scripted_surface_rejects_mixed_native_tools() -> None:
    schemas = [
        *_scripted_context()["provider_tool_schemas"],
        {
            "name": "core.get_active_document",
            "description": "Inspect the active document.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]
    assert session._fixed_scripted_surface("PartDesignWorkbench", schemas) is None


def test_codex_dynamic_tools_preserve_vibecad_namespaces_and_schema() -> None:
    tools, names = provider._codex_dynamic_tool_surface(_scripted_context())
    assert names == {("vibescript", "inspect_model"): "vibescript.inspect_model"}
    assert tools == [
        {
            "type": "namespace",
            "name": "vibescript",
            "description": "VibeCAD vibescript operations available now.",
            "tools": [
                {
                    "type": "function",
                    "name": "inspect_model",
                    "description": "Inspect one VibeScript model.",
                    "deferLoading": False,
                    "inputSchema": _scripted_context()["provider_tool_schemas"][0][
                        "parameters"
                    ],
                }
            ],
        }
    ]


def test_codex_images_use_the_bounded_inline_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "viewport.png"
    screenshot.write_bytes(b"x" * (provider.CODEX_INLINE_IMAGE_MAX_BYTES + 1))
    encoded = b"\xff\xd8" + (b"v" * 1024) + b"\xff\xd9"
    calls: list[tuple[Path, int, bool]] = []

    def encode(
        path: Path,
        *,
        max_bytes: int,
        prefer_jpeg: bool,
    ) -> tuple[str, bytes, dict]:
        calls.append((path, max_bytes, prefer_jpeg))
        return (
            "image/jpeg",
            encoded,
            {
                "resized": True,
                "encoded_format": "jpg",
                "image_size": [1280, 812],
                "size_bytes": len(encoded),
            },
        )

    monkeypatch.setattr(provider, "_provider_encoded_image_payload", encode)
    context = {
        "view_screenshot": {
            "captured": True,
            "new_observation": True,
            "path": str(screenshot),
        }
    }

    turn_input = provider._codex_turn_input("Inspect it.", context)
    tool_output = provider._codex_tool_image_content_items(context)

    assert calls == [
        (screenshot, provider.CODEX_INLINE_IMAGE_MAX_BYTES, True),
        (screenshot, provider.CODEX_INLINE_IMAGE_MAX_BYTES, True),
    ]
    turn_image = turn_input[-1]
    tool_image = tool_output[-1]
    assert turn_image["type"] == "image"
    assert tool_image["type"] == "inputImage"
    assert turn_image["url"] == tool_image["imageUrl"]
    assert turn_image["url"].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(turn_image["url"].partition(",")[2]) == encoded
    assert len(encoded) <= provider.CODEX_INLINE_IMAGE_MAX_BYTES


def test_codex_thread_config_disables_non_vibecad_tool_surfaces() -> None:
    config = codex.vibecad_thread_config()
    assert config["orchestrator.mcp.enabled"] is False
    assert config["orchestrator.skills.enabled"] is False
    assert config["project_doc_max_bytes"] == 0
    assert config["tools.experimental_request_user_input.enabled"] is False
    assert config["skills.include_instructions"] is False
    assert config["features.shell_tool"] is False
    assert config["features.plugins"] is False
    assert config["web_search"] == "disabled"


def test_codex_thread_config_enables_only_web_and_skill_capabilities() -> None:
    config = codex.vibecad_thread_config(
        web_search_enabled=True,
        skills_enabled=True,
    )
    assert config["web_search"] == "live"
    assert config["skills.bundled.enabled"] is True
    assert config["skills.include_instructions"] is True
    assert config["orchestrator.skills.enabled"] is False
    assert config["features.shell_tool"] is False
    assert config["features.browser_use"] is False
    assert config["features.computer_use"] is False
    assert config["features.plugins"] is False


def test_provider_capability_preferences_have_explicit_defaults() -> None:
    settings = preferences.VibeCADSettings()
    assert settings.web_search_enabled is False
    assert settings.design_review_enabled is True
    assert settings.codex_skills_enabled is False


def test_codex_skill_reader_is_scoped_to_enabled_skill_directory(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills" / "design-review"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Design review\n", encoding="utf-8")
    reference = skill_dir / "references" / "checks.md"
    reference.parent.mkdir()
    reference.write_text("Check interfaces.\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("private\n", encoding="utf-8")
    catalog = {
        "design-review": codex.CodexSkill(
            name="design-review",
            description="Review a design.",
            path=skill_file,
        )
    }

    main = codex.read_codex_skill_resource(catalog, name="design-review")
    assert main == {
        "ok": True,
        "skill": "design-review",
        "resource": "SKILL.md",
        "content": "# Design review\n",
    }
    nested = codex.read_codex_skill_resource(
        catalog,
        name="design-review",
        resource="references/checks.md",
    )
    assert nested["ok"] is True
    assert nested["content"] == "Check interfaces.\n"
    escaped = codex.read_codex_skill_resource(
        catalog,
        name="design-review",
        resource="../../outside.md",
    )
    assert escaped["ok"] is False
    assert "inside the skill directory" in escaped["error"]


def test_codex_skill_catalog_uses_personal_root_and_enabled_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vibecad_home = tmp_path / "vibecad-codex"
    personal_home = tmp_path / "personal-codex"
    personal_root = personal_home / "skills"
    personal_root.mkdir(parents=True)
    skill_file = personal_root / "cad-review" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("# CAD review\n", encoding="utf-8")
    monkeypatch.setenv(codex.CODEX_HOME_ENV, str(vibecad_home))
    monkeypatch.setenv("CODEX_HOME", str(personal_home))

    class _Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def request(self, method: str, params: dict, timeout: float) -> dict:
            self.calls.append((method, params))
            if method == "skills/extraRoots/set":
                return {}
            if method == "skills/list":
                return {
                    "data": [
                        {
                            "skills": [
                                {
                                    "name": "cad-review",
                                    "description": "Review CAD intent.",
                                    "path": str(skill_file),
                                    "enabled": True,
                                },
                                {
                                    "name": "disabled",
                                    "description": "Disabled.",
                                    "path": str(skill_file),
                                    "enabled": False,
                                },
                            ]
                        }
                    ]
                }
            raise AssertionError(method)

    client = _Client()
    catalog = codex.load_codex_skill_catalog(client, cwd=tmp_path)
    assert list(catalog) == ["cad-review"]
    assert client.calls[0] == (
        "skills/extraRoots/set",
        {"extraRoots": [str(personal_root.resolve())]},
    )
    assert client.calls[1] == (
        "skills/list",
        {"cwds": [str(tmp_path)], "forceReload": True},
    )


def test_current_subscription_reasoning_efforts_are_preserved() -> None:
    assert preferences.normalize_reasoning_effort("max") == "max"
    assert preferences.normalize_reasoning_effort("ultra") == "ultra"


def test_choose_provider_carries_codex_capability_preferences() -> None:
    class _Service:
        def provider_name(self) -> str:
            return "chatgpt"

        def auth_state(self):
            return object()

        def provider_model(self) -> str:
            return "gpt-test"

        def provider_reasoning_effort(self) -> str:
            return "high"

        def web_search_enabled(self) -> bool:
            return True

        def codex_skills_enabled(self) -> bool:
            return True

    selected = session.choose_provider(_Service())
    assert isinstance(selected, provider.ChatGPTSubscriptionProvider)
    assert selected.web_search_enabled is True
    assert selected.skills_enabled is True


@pytest.mark.parametrize(
    ("provider_name", "provider_type"),
    [
        ("openai", provider.OpenAIProvider),
        ("anthropic", provider.AnthropicProvider),
    ],
)
def test_choose_provider_enables_web_search_for_api_providers(
    provider_name: str,
    provider_type: type,
) -> None:
    class _Auth:
        can_call_provider = True

    class _Service:
        def provider_name(self) -> str:
            return provider_name

        def auth_state(self):
            return _Auth()

        def provider_model(self) -> str:
            return "test-model"

        def provider_api_key(self) -> str:
            return "test-key"

        def provider_reasoning_effort(self) -> str:
            return "high"

        def provider_base_url(self):
            return None

        def web_search_enabled(self) -> bool:
            return True

    selected = session.choose_provider(_Service())
    assert isinstance(selected, provider_type)
    assert selected.web_search_enabled is True


def test_codex_client_initializes_and_reads_account_from_json_rpc(
    tmp_path: Path,
) -> None:
    fake_server = tmp_path / "fake_app_server.py"
    fake_server.write_text(
        """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        continue
    if method == "initialize":
        result = {"userAgent": "fake"}
    elif method == "account/read":
        result = {"account": None, "requiresOpenaiAuth": True}
    else:
        print(json.dumps({"id": request_id, "error": {"code": -1, "message": method}}), flush=True)
        continue
    print(json.dumps({"id": request_id, "result": result}), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    command = codex.CodexRuntimeCommand(
        argv=(sys.executable, str(fake_server)),
        executable=Path(sys.executable),
        source="test",
        version="test",
    )
    with codex.CodexAppServerClient(command=command) as client:
        result = client.request("account/read", {"refreshToken": False})
    assert result == {"account": None, "requiresOpenaiAuth": True}
