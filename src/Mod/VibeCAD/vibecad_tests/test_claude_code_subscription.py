# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused contracts for the Claude Code subscription provider."""

from __future__ import annotations

from pathlib import Path

import VibeCADAuth as auth
import VibeCADPreferences as preferences
import VibeCADProvider as provider
import VibeCADSession as session

OAUTH_TOKEN = "sk-ant-oat01-example-token"
API_KEY = "sk-ant-api03-example-key"


class TestProviderSpec:
    def test_registered_with_oauth_auth_kind(self):
        spec = auth.provider_spec("claude-code")
        assert spec.display_name == "Claude Code subscription"
        assert spec.auth_kind == "oauth_token"
        assert spec.env_var == "CLAUDE_CODE_OAUTH_TOKEN"
        assert spec.uses_api_key
        assert spec.is_anthropic_api
        assert spec.credential_label == "OAuth token"

    def test_auth_headers_use_bearer_and_oauth_beta(self):
        headers = auth.provider_spec("claude-code").auth_headers(OAUTH_TOKEN)
        assert headers["Authorization"] == f"Bearer {OAUTH_TOKEN}"
        assert headers["anthropic-version"] == auth.ANTHROPIC_API_VERSION
        assert headers["anthropic-beta"] == auth.ANTHROPIC_OAUTH_BETA
        assert "x-api-key" not in headers

    def test_anthropic_headers_unchanged(self):
        headers = auth.provider_spec("anthropic").auth_headers(API_KEY)
        assert headers == {
            "x-api-key": API_KEY,
            "anthropic-version": auth.ANTHROPIC_API_VERSION,
        }

    def test_models_url_follows_anthropic_convention(self):
        spec = auth.provider_spec("claude-code")
        assert spec.models_url_for() == "https://api.anthropic.com/v1/models"
        assert spec.models_url_for("https://proxy.local") == (
            "https://proxy.local/v1/models"
        )


class TestCredentialResolution:
    def test_env_var_resolves_token(self):
        credential = auth.resolve_auth_credential(
            env={"CLAUDE_CODE_OAUTH_TOKEN": OAUTH_TOKEN}, provider="claude-code"
        )
        assert credential is not None
        assert credential.value == OAUTH_TOKEN
        assert credential.source == "environment"

    def test_dotenv_resolves_token(self, tmp_path: Path):
        dotenv = tmp_path / "claude.env"
        dotenv.write_text(f'CLAUDE_CODE_OAUTH_TOKEN="{OAUTH_TOKEN}"\n')
        credential = auth.resolve_auth_credential(
            env={}, dotenv_path=dotenv, provider="claude-code"
        )
        assert credential is not None
        assert credential.value == OAUTH_TOKEN

    def test_missing_token_reports_oauth_wording(self):
        state = auth.resolve_auth_state(env={}, provider="claude-code")
        assert state.status is auth.AuthStatus.NOT_CONFIGURED
        assert "OAuth token" in state.message

    def test_token_detection(self):
        assert auth.is_claude_code_oauth_token(OAUTH_TOKEN)
        assert not auth.is_claude_code_oauth_token(API_KEY)
        assert not auth.is_claude_code_oauth_token("")
        assert not auth.is_claude_code_oauth_token(None)


class TestAnthropicClientAuthKwargs:
    def test_oauth_token_becomes_bearer_auth(self):
        kwargs = provider.anthropic_client_auth_kwargs(OAUTH_TOKEN)
        assert kwargs == {
            "auth_token": OAUTH_TOKEN,
            "default_headers": {"anthropic-beta": auth.ANTHROPIC_OAUTH_BETA},
        }

    def test_api_key_stays_api_key(self):
        assert provider.anthropic_client_auth_kwargs(API_KEY) == {"api_key": API_KEY}

    def test_missing_credential_defers_to_sdk_resolution(self):
        assert provider.anthropic_client_auth_kwargs(None) == {}
        assert provider.anthropic_client_auth_kwargs("") == {}


class TestPreferences:
    def test_default_model_is_fable(self):
        assert preferences.DEFAULT_CLAUDE_CODE_MODEL == "claude-fable-5"
        assert preferences.DEFAULT_MODELS["claude-code"] == "claude-fable-5"

    def test_active_model_defaults_to_fable(self):
        settings = preferences.VibeCADSettings(provider="claude-code")
        assert settings.active_model == "claude-fable-5"
        assert settings.model_for("claude-code") == "claude-fable-5"

    def test_blank_model_falls_back_to_fable(self):
        settings = preferences.VibeCADSettings(
            provider="claude-code", claude_code_model="   "
        )
        assert settings.active_model == "claude-fable-5"

    def test_subscription_ignores_base_url_overrides(self):
        settings = preferences.VibeCADSettings(
            provider="claude-code",
            anthropic_base_url="https://proxy.local",
            openai_base_url="https://other.local/v1",
        )
        assert settings.active_base_url is None
        assert settings.base_url_for("claude-code") is None

    def test_intent_memory_model_defaults_to_active_model(self):
        settings = preferences.VibeCADSettings(provider="claude-code")
        assert settings.intent_memory_model_for("claude-code") == "claude-fable-5"
        override = preferences.VibeCADSettings(
            provider="claude-code",
            claude_code_intent_memory_model="claude-sonnet-5",
        )
        assert override.intent_memory_model_for("claude-code") == "claude-sonnet-5"

    def test_normalize_provider_accepts_claude_code(self):
        assert preferences.normalize_provider("claude-code") == "claude-code"
        assert preferences.normalize_provider("Claude-Code") == "claude-code"


class _FakeService:
    """Just enough of VibeCADService for choose_provider."""

    def __init__(self, can_call: bool = True):
        self._can_call = can_call

    def provider_name(self) -> str:
        return "claude-code"

    def auth_state(self):
        status = (
            auth.AuthStatus.CONFIGURED_UNVERIFIED
            if self._can_call
            else auth.AuthStatus.NOT_CONFIGURED
        )
        return auth.AuthState(status)

    def provider_model(self) -> str:
        return "claude-fable-5"

    def provider_api_key(self) -> str | None:
        return OAUTH_TOKEN

    def provider_reasoning_effort(self) -> str:
        return "high"

    def provider_base_url(self) -> str | None:
        return None

    def web_search_enabled(self) -> bool:
        return False

    def codex_skills_enabled(self) -> bool:
        return False


class TestChooseProvider:
    def test_claude_code_rides_the_anthropic_adapter(self):
        chosen = session.choose_provider(_FakeService())
        assert isinstance(chosen, session.AnthropicProvider)
        assert chosen.model == "claude-fable-5"
        assert chosen.api_key == OAUTH_TOKEN
        assert chosen.base_url is None

    def test_unconfigured_token_falls_back_offline(self):
        chosen = session.choose_provider(_FakeService(can_call=False))
        assert isinstance(chosen, session.OfflineProvider)


class TestDesignReviewDispatch:
    def test_claude_code_routes_to_the_anthropic_review_child(self, monkeypatch):
        import VibeCADDesignReview as review

        captured: dict[str, object] = {}

        def fake_subprocess(**kwargs):
            captured.update(kwargs)
            return provider.ProviderResult(final_output="{}", raw={})

        monkeypatch.setattr(review, "_run_provider_subprocess", fake_subprocess)
        monkeypatch.setattr(review, "_validate_review", lambda payload: {"ok": True})
        review.run_design_review(
            provider="claude-code",
            model="claude-fable-5",
            api_key=OAUTH_TOKEN,
            base_url=None,
            reasoning_effort="high",
            customer_intent="intent",
            design_draft="draft",
            context={},
        )
        assert captured["child_main"] is review._anthropic_review_child_main
        assert captured["api_key"] == OAUTH_TOKEN
        assert captured["model"] == "claude-fable-5"
