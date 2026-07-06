#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Ask the configured OpenAI model to critique VibeCAD tool/context shape."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import FreeCAD as App
import requests
from PySide import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "release" / "Mod" / "VibeCAD"))

from VibeCADCore import VibeCADService
from VibeCADSession import provider_safe_tool_schemas


TRACE_PATH = Path("/tmp/vibecad-live-progress.jsonl")


def _read_recent_trace() -> list[dict]:
    if not TRACE_PATH.exists():
        return []
    rows = []
    for line in TRACE_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _extract_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def main() -> int:
    service = VibeCADService()
    api_key = service.provider_api_key()
    if not api_key:
        print(json.dumps({"ok": False, "error": "No configured OpenAI API key."}, indent=2))
        return 1

    workbenches = ["PartDesignWorkbench", "SketcherWorkbench", "PartWorkbench", "AssemblyWorkbench"]
    tool_surfaces = {
        name: provider_safe_tool_schemas(service, name)
        for name in workbenches
    }
    context = {
        "provider": service.provider_context_summary().get("provider", {}),
        "tool_surfaces": tool_surfaces,
        "tool_shape_report": service.tool_shape_report("PartDesignWorkbench"),
        "recent_failed_live_trace": _read_recent_trace(),
    }
    prompt = (
        "You are the live model that must drive VibeCAD tools to build complex CAD. "
        "Critique the tool/context shape below for complex geometry as the default: "
        "rocket engine, robot arm, drone, vehicle, aerospace and marine parts. "
        "Do not be polite; be specific and operational. The prior live run stalled "
        "after workbench switches, sketch circles, a checkpointed pad, and repeated "
        "inspection. Explain exactly what result fields, schemas, next-action hints, "
        "state summaries, and recovery affordances would have prevented that. "
        "Include happy-path and unhappy-path tool result shapes for sketch->pad, "
        "pad failure, checkpoint, workbench switch, assembly creation, screenshot "
        "inspection, and iterative correction. Return concrete JSON-like field "
        "names and priority order for implementation.\n\n"
        f"VibeCAD context/tool data:\n{json.dumps(context, indent=2, sort_keys=True, default=str)[:60000]}"
    )

    body = {
        "model": service.provider_model(),
        "input": prompt,
        "reasoning": {"effort": service.provider_reasoning_effort()},
        "max_output_tokens": 6000,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=240,
    )
    payload = response.json()
    result = {
        "ok": response.ok,
        "status_code": response.status_code,
        "model": service.provider_model(),
        "reasoning_effort": service.provider_reasoning_effort(),
        "critique": _extract_text(payload),
    }
    if response.ok and not result["critique"]:
        result["raw_response_excerpt"] = json.dumps(payload, default=str)[:12000]
    if not response.ok:
        result["error"] = payload
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if response.ok else 1


def run_and_exit() -> None:
    code = 1
    try:
        code = main()
    except Exception:
        print(json.dumps({"ok": False, "traceback": traceback.format_exc()}, indent=2))
    finally:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.exit(code)


QtCore.QTimer.singleShot(1000, run_and_exit)
