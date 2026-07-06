#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Live OpenAI smoke for phase-scoped VibeCAD tool surfaces.

Run with FreeCAD/FreeCADCmd from the repository root. The smoke creates an
approved design-phase project fixture, exposes the Sketcher provider surface,
and asks the live model to add a four-hole mounting pattern to the existing
active sketch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VIBECAD_MOD = ROOT / "build" / "release" / "Mod" / "VibeCAD"
if str(VIBECAD_MOD) not in sys.path:
    sys.path.insert(0, str(VIBECAD_MOD))

import FreeCAD as App  # noqa: E402

from VibeCADCore import VibeCADService  # noqa: E402
from VibeCADProvider import (  # noqa: E402
    DEFAULT_OPENAI_REQUEST_DUMP_DIR,
    OPENAI_REQUEST_DUMP_DIR_ENV,
    OpenAIAgentsProvider,
    ProviderUnavailable,
)
from VibeCADSession import make_provider_tool_runner, provider_safe_tool_schemas  # noqa: E402


RESULT_PATH_ENV = "VIBECAD_PHASE_TOOL_SMOKE_RESULT"
TIMEOUT_ENV = "VIBECAD_PHASE_TOOL_SMOKE_TIMEOUT"
MODEL_ENV = "VIBECAD_PHASE_TOOL_SMOKE_MODEL"
REASONING_EFFORT_ENV = "VIBECAD_PHASE_TOOL_SMOKE_REASONING_EFFORT"


PROMPT = (
    "In the current active Sketcher sketch, add a centered 2 by 2 mounting "
    "hole pattern for M4 screws. The holes are 4.5 mm diameter with 50 mm "
    "horizontal spacing and 20 mm vertical spacing. Make the result fully "
    "constrained and named for later pocketing. Edit the current sketch only; "
    "do not create or open any document and do not create a new body."
)


def _optional_float_env(name: str, default: float | None = None) -> float | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _result_path() -> Path:
    configured = os.environ.get(RESULT_PATH_ENV)
    if configured and configured.strip():
        return Path(configured).expanduser()
    return Path("/tmp/vibecad-live-phase-tool-surface-smoke.json")


def _latest_request_dump_summary() -> dict[str, Any]:
    dump_dir = Path(
        os.environ.get(OPENAI_REQUEST_DUMP_DIR_ENV, "").strip()
        or DEFAULT_OPENAI_REQUEST_DUMP_DIR
    ).expanduser()
    latest = dump_dir / "latest-openai-request.json"
    if not latest.is_file():
        return {"exists": False, "path": str(latest)}
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "path": str(latest), "read_error": str(exc)}
    tools = data.get("agent", {}).get("tools", []) if isinstance(data, dict) else []
    tool_names = [
        item.get("function_name")
        for item in tools
        if isinstance(item, dict) and item.get("function_name")
    ] if isinstance(tools, list) else []
    visible_context = data.get("model_visible_context", {}) if isinstance(data, dict) else {}
    return {
        "exists": True,
        "path": str(latest),
        "schema": data.get("schema") if isinstance(data, dict) else None,
        "model": data.get("model") if isinstance(data, dict) else None,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "has_core_create_new_document": "core_create_new_document" in tool_names,
        "has_core_open_document": "core_open_document" in tool_names,
        "has_sketcher_add_hole_pattern": "sketcher_add_hole_pattern" in tool_names,
        "has_available_tools_context": bool(
            isinstance(visible_context, dict)
            and (
                "available_tools" in visible_context
                or "available_tools_workbench" in visible_context
            )
        ),
        "has_tool_menu_context": bool(
            isinstance(visible_context, dict)
            and (
                "provider_function_tools" in visible_context
                or "provider_tool_surface" in visible_context
                or "tool_shape_report" in visible_context
            )
        ),
    }


def _close_documents() -> None:
    for document in list(App.listDocuments().values()):
        try:
            App.closeDocument(document.Name)
        except Exception:
            pass


def _prepare_fixture(service: VibeCADService) -> str | None:
    App.newDocument("VibeCADHolePatternLiveSmoke")
    service.update_intent_brief(
        title="Live hole pattern smoke",
        summary="Verify phase-scoped Sketcher tools for an existing mounting sketch.",
        requirements={
            "purpose": "create a reusable mounting hole pattern in an existing sketch",
            "critical_dimensions": "4.5 mm M4 clearance holes, 50 mm by 20 mm spacing",
            "interfaces": "four mounting holes for fasteners",
            "loads": "light mounting bracket test fixture",
            "materials_process": "generic machined or printed plate",
            "tolerances": "nominal CAD smoke test tolerances",
            "environment": "development smoke test",
            "acceptance_criteria": [
                "fully constrained named hole profiles in the current sketch"
            ],
        },
        readiness_score=100,
        ready_for_next_phase=True,
    )
    service.approve_intent_brief()
    service.set_phase("design", reason="live phase-scoped smoke", requested_by="test")
    body = service.registry.call("partdesign.create_body", label="Existing Mounting Plate")
    sketch = service.registry.call(
        "partdesign.create_sketch",
        label="Existing Mounting Hole Sketch",
        plane="XY_Plane",
        body_name=body.get("active_body"),
    )
    return sketch.get("active_sketch") if isinstance(sketch, dict) else None


def main() -> int:
    result_path = _result_path()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _close_documents()
        service = VibeCADService()
        sketch_name = _prepare_fixture(service)
        context = service.provider_context_summary()
        context["workbench"] = "SketcherWorkbench"
        context["provider_tool_schemas"] = provider_safe_tool_schemas(
            service,
            "SketcherWorkbench",
        )
        context["provider_tool_schemas_workbench"] = "SketcherWorkbench"
        context["vibecad_loop"] = {
            "mode": "live_phase_tool_surface_smoke",
            "goal": "Modify the current active sketch only.",
            "next_step": (
                "Add the requested hole pattern with the best native Sketcher "
                "tool available."
            ),
            "remaining_outcomes": [
                "current sketch contains four M4 clearance holes",
                "hole centers and radii are fully constrained",
                "geometry is named for later PartDesign pocketing",
            ],
        }
        tool_trace: list[dict[str, Any]] = []
        request_policy = {
            "mode": "modify_existing",
            "preserve_existing_model": True,
            "document_object_count_at_start": service.document_summary().get(
                "object_count",
                0,
            ),
        }
        runner = make_provider_tool_runner(
            service,
            workbench="SketcherWorkbench",
            tool_trace=tool_trace,
            request_policy=request_policy,
        )
        provider = OpenAIAgentsProvider(
            model=os.environ.get(MODEL_ENV) or service.provider_model(),
            api_key=service.provider_api_key(),
            reasoning_effort=(
                os.environ.get(REASONING_EFFORT_ENV)
                or service.provider_reasoning_effort()
            ),
            timeout_seconds=_optional_float_env(TIMEOUT_ENV, 120.0),
        )
        safe_tool_names = [
            schema.get("name")
            for schema in context["provider_tool_schemas"]
            if isinstance(schema, dict)
        ]
        response = provider.run(PROMPT, context, tool_runner=runner)
        tool_names = [item.get("tool_name") for item in tool_trace]
        sketch = App.ActiveDocument.getObject(sketch_name) if sketch_name else None
        profile_status = service._sketch_profile_status(sketch) if sketch is not None else {}
        sketcher = service.sketcher_summary(sketch_name)
        result = {
            "ok": True,
            "provider": "OpenAIAgentsProvider",
            "model": provider.model,
            "reasoning_effort": provider.reasoning_effort,
            "prompt": PROMPT,
            "final_output": response.final_output,
            "tool_names": tool_names,
            "used_hole_pattern": any(
                name == "sketcher.add_hole_pattern" for name in tool_names
            ),
            "circle_tool_count": sum(
                1 for name in tool_names if name == "sketcher.add_circle"
            ),
            "constraint_tool_count": sum(
                1 for name in tool_names if name == "sketcher.add_constraint"
            ),
            "exposed_tool_count": len(safe_tool_names),
            "exposed_tools": safe_tool_names,
            "exposed_core_create_new_document": (
                "core.create_new_document" in safe_tool_names
            ),
            "exposed_core_open_document": "core.open_document" in safe_tool_names,
            "exposed_hole_pattern": "sketcher.add_hole_pattern" in safe_tool_names,
            "profile_status": profile_status,
            "sketcher": sketcher,
            "request_dump": _latest_request_dump_summary(),
            "failures": [],
        }
        if not result["used_hole_pattern"]:
            result["failures"].append("live model did not call sketcher.add_hole_pattern")
        if result["exposed_core_create_new_document"] or result["exposed_core_open_document"]:
            result["failures"].append("document management tools leaked into Sketcher surface")
        if not result["exposed_hole_pattern"]:
            result["failures"].append("sketcher.add_hole_pattern was not exposed")
        if profile_status.get("degrees_of_freedom") not in (0, "0"):
            result["failures"].append("sketch did not become fully constrained")
        result["ok"] = not result["failures"]
    except ProviderUnavailable as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "request_dump": _latest_request_dump_summary(),
        }
    except Exception:
        result = {"ok": False, "traceback": traceback.format_exc()}
    finally:
        try:
            _close_documents()
        except Exception:
            pass
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ in {"__main__", "__builtin__", "builtins"}:
    raise SystemExit(main())
