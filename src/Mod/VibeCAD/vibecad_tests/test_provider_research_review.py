# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused contracts for provider-native research and isolated design review."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import VibeCADDesignReview as design_review
import VibeCADProvider as provider


def _review(*, verdict: str = "ready", severity: str | None = None) -> dict:
    findings = []
    if severity:
        findings.append(
            {
                "severity": severity,
                "category": "interfaces",
                "issue": "The mating interface is undefined.",
                "consequence": "The components cannot be assembled reliably.",
                "required_change": "Define datums, fit, and retained clearances.",
            }
        )
    return {
        "verdict": verdict,
        "summary": "The proposal is internally coherent.",
        "strengths": ["The component boundaries are explicit."],
        "findings": findings,
        "required_revisions": [],
        "questions_for_user": [],
    }


def test_openai_compatible_web_search_uses_the_hosted_responses_tool() -> None:
    cad_tool = {"type": "function", "name": "vibecad_test"}
    assert provider._openai_request_tools([cad_tool], False) == [cad_tool]
    assert provider._openai_request_tools([cad_tool], True) == [
        cad_tool,
        {"type": "web_search"},
    ]


def test_anthropic_web_search_uses_direct_current_server_tool() -> None:
    cad_tool = {"name": "vibecad_test", "input_schema": {"type": "object"}}
    assert provider._anthropic_request_tools([cad_tool], False) == [cad_tool]
    assert provider._anthropic_request_tools([cad_tool], True) == [
        cad_tool,
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": 5,
            "allowed_callers": ["direct"],
        },
    ]


def test_openai_citations_are_rendered_as_clickable_markdown_sources() -> None:
    annotation = {
        "type": "url_citation",
        "url": "https://example.com/bearing",
        "title": "Bearing catalog",
    }
    content = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Use the current catalog load rating.",
                    "annotations": [annotation],
                }
            ],
        }
    )
    response = SimpleNamespace(
        output_text="Use the current catalog load rating.", output=[content]
    )
    text = provider._openai_final_text(response)
    assert "[Bearing catalog](https://example.com/bearing)" in text


def test_xai_response_level_citations_are_rendered_without_special_includes() -> None:
    response = SimpleNamespace(
        output_text="Use the current catalog load rating.",
        output=[],
        citations=["https://example.com/xai-bearing"],
    )
    text = provider._openai_final_text(response)
    assert "[https://example.com/xai-bearing]" in text


def test_anthropic_citations_are_rendered_as_clickable_markdown_sources() -> None:
    block = SimpleNamespace(
        type="text",
        text="Use the current material datasheet.",
        model_dump=lambda **_kwargs: {
            "type": "text",
            "text": "Use the current material datasheet.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://example.com/material",
                    "title": "Material datasheet",
                }
            ],
        },
    )
    text = provider._anthropic_final_text([block])
    assert "[Material datasheet](https://example.com/material)" in text


def test_anthropic_server_tool_blocks_round_trip_without_losing_state() -> None:
    block = SimpleNamespace(
        type="web_search_tool_result",
        model_dump=lambda **_kwargs: {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://example.com",
                    "encrypted_content": "opaque",
                }
            ],
        },
    )
    assert provider._anthropic_assistant_request_content([block]) == [
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://example.com",
                    "encrypted_content": "opaque",
                }
            ],
        }
    ]


def test_design_review_rejects_a_false_ready_verdict() -> None:
    with pytest.raises(RuntimeError, match="blocking or major"):
        design_review._validate_review(_review(verdict="ready", severity="major"))


def test_design_review_accepts_structured_revision_findings() -> None:
    review = _review(verdict="revise", severity="blocking")
    assert design_review._validate_review(review) == review


def test_anthropic_review_schema_removes_only_unsupported_constraints() -> None:
    compiled = design_review._anthropic_strict_schema(
        design_review.REVIEW_RESULT_SCHEMA
    )
    assert "maxItems" not in str(compiled)
    assert "minLength" not in str(compiled)
    assert compiled["required"] == design_review.REVIEW_RESULT_SCHEMA["required"]
    assert compiled["properties"]["verdict"]["enum"] == ["ready", "revise"]


def test_design_review_prompt_contains_only_review_inputs_and_live_facts() -> None:
    prompt = design_review._review_prompt(
        "Create a manufacturable impeller with a retained shaft interface.",
        "A revolved hub carries separately authored full and splitter blades. "
        "Blade roots overlap the hub and every repeated interface is verified.",
        {
            "cad_state": {"document": "Impeller"},
            "conversation": {"conversation": [{"content": "not duplicated"}]},
        },
    )
    assert '"customer_intent"' in prompt
    assert '"design_draft"' in prompt
    assert '"cad_state"' in prompt
    assert "not duplicated" not in prompt
