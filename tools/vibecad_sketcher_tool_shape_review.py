#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Ask the live VibeCAD AI to review the Sketcher tool surface."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import FreeCAD as App
try:
    import FreeCADGui as Gui
except Exception:
    Gui = None

from VibeCADCore import VibeCADService
from VibeCADProvider import OpenAIAgentsProvider
from VibeCADSession import make_provider_tool_runner, provider_safe_tool_schemas


PROMPT = (
    "Review the active VibeCAD Sketcher tool surface as an AI CAD operator. "
    "Use the current FreeCAD context and available function tools. Decide whether "
    "the Sketcher tools are clear enough for you to create and revise accurate, "
    "fully constrained sketches in small human-like steps. Do not create geometry. "
    "For each actionable missing, ambiguous, or poorly shaped Sketcher tool issue, "
    "call core.report_tool_shape_gap with the specific tool or missing tool class, "
    "why it blocks high-quality sketching, and the schema/result data you need. "
    "Finish with a concise prioritized review."
)


def _optional_float_env(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return float(value)


def main() -> int:
    result_path = Path(
        os.environ.get("VIBECAD_SKETCHER_TOOL_REVIEW_RESULT")
        or "/tmp/vibecad-sketcher-tool-shape-review.json"
    )
    try:
        print("vibecad_sketcher_tool_shape_review: starting", flush=True)
        for document in list(App.listDocuments().values()):
            App.closeDocument(document.Name)
        App.newDocument("VibeCADSketcherToolReview")
        if Gui is not None:
            try:
                Gui.activateWorkbench("SketcherWorkbench")
            except Exception:
                pass

        service = VibeCADService()
        provider = OpenAIAgentsProvider(
            model=os.environ.get("VIBECAD_REVIEW_MODEL") or service.provider_model(),
            api_key=service.provider_api_key(),
            reasoning_effort=(
                os.environ.get("VIBECAD_REVIEW_REASONING_EFFORT")
                or service.provider_reasoning_effort()
            ),
            timeout_seconds=_optional_float_env("VIBECAD_REVIEW_TURN_TIMEOUT"),
        )
        before = service.tool_shape_report("SketcherWorkbench")
        context = service.provider_context_summary()
        context["workbench"] = "SketcherWorkbench"
        context["provider_tool_schemas"] = provider_safe_tool_schemas(service, "SketcherWorkbench")
        context["provider_tool_schemas_workbench"] = "SketcherWorkbench"
        context["vibecad_loop"] = {
            "goal": "Review Sketcher tool shape and report gaps.",
            "next_step": "Inspect tool schemas, call core.report_tool_shape_gap for actionable gaps, then summarize.",
            "remaining_outcomes": [
                "Identify unclear Sketcher tool schemas.",
                "Identify missing native Sketcher tool classes.",
                "Identify missing result data needed for iteration.",
            ],
        }
        tool_trace = []
        tool_runner = make_provider_tool_runner(
            service,
            workbench="SketcherWorkbench",
            tool_trace=tool_trace,
        )
        print("vibecad_sketcher_tool_shape_review: calling provider", flush=True)
        response = provider.run(PROMPT, context, tool_runner=tool_runner)
        after = service.tool_shape_report("SketcherWorkbench")
        tool_names = [
            schema["name"]
            for schema in provider_safe_tool_schemas(service, "SketcherWorkbench")
        ]
        result = {
            "ok": True,
            "provider": "OpenAIAgentsProvider",
            "error": None,
            "model": provider.model,
            "reasoning_effort": provider.reasoning_effort,
            "sketcher_tool_count": len(tool_names),
            "sketcher_tools": tool_names,
            "tool_trace": tool_trace,
            "final_output": response.final_output,
            "feedback_before": before.get("recent_tool_shape_feedback", []),
            "feedback_after": after.get("recent_tool_shape_feedback", []),
        }
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ in {"__main__", "__builtin__", "builtins", "vibecad_sketcher_tool_shape_review"}:
    raise SystemExit(main())
