#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run a live VibeCAD provider acceptance scenario in FreeCAD GUI."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def _write_boot_event(event: str) -> None:
    path_text = os.environ.get("VIBECAD_ACCEPTANCE_PROGRESS_PATH")
    if not path_text:
        return
    with Path(path_text).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event}, sort_keys=True) + "\n")
        handle.flush()


_write_boot_event("boot_before_freecad_import")
import FreeCAD as App
import FreeCADGui as Gui
_write_boot_event("boot_after_freecad_import")

_write_boot_event("boot_before_vibecad_import")
from VibeCADCore import VibeCADService
from VibeCADProvider import DEFAULT_OPENAI_REQUEST_DUMP_DIR, OPENAI_REQUEST_DUMP_DIR_ENV
from VibeCADProvider import OpenAIAgentsProvider
from VibeCADSession import run_prompt
_write_boot_event("boot_after_vibecad_import")


def _last_phrase_index(text: str, phrases: tuple[str, ...]) -> int:
    return max((text.rfind(phrase) for phrase in phrases), default=-1)


def _last_checkpoint_index(text: str) -> int:
    return _last_phrase_index(
        text,
        (
            "progress checkpoint",
            "checkpoint progress",
            "requested a checkpoint",
            "checkpoint before",
            "checkpoint so the tool context can refresh",
        ),
    )


def _last_completion_index(text: str) -> int:
    return _last_phrase_index(
        text,
        (
            "completed",
            "final inspected state",
            "final model",
            "coherent cad",
            "is now a coherent",
        ),
    )


def _final_output_unresolved_reasons(text: str) -> list[str]:
    text = text.lower()
    completion_index = _last_completion_index(text)
    if completion_index >= 0:
        text = text[completion_index:]
    phrases = {
        "checkpoint": (
            "progress checkpoint",
            "checkpoint progress",
            "requested a checkpoint",
            "checkpoint before",
            "checkpoint so the tool context can refresh",
        ),
        "next-step": (
            "required next inspection",
            "next step after refresh",
            "next step after context refresh",
            "next step can",
            "next step:",
            "next steps:",
            "to continue",
            "continue by",
        ),
        "ineffective-geometry": (
            "not actually",
            "not subtracting",
            "not cutting",
            "remained unchanged",
            "did not change",
            "didn't change",
            "ineffective",
            "attempted pockets",
            "can be recreated",
        ),
        "unable": (
            "could not",
            "cannot",
            "can't",
            "not currently",
            "no document objects",
            "no objects were created",
        ),
        "timeout": (
            "autonomous provider loop reached",
            "configured 600 second limit",
            "before completion",
            "provider_total_timeout",
        ),
    }
    return [
        reason
        for reason, reason_phrases in phrases.items()
        if any(phrase in text for phrase in reason_phrases)
    ]


COMPLETION_DIRECTIVE = (
    "Complete a coherent first-pass CAD model in this run. Prioritize the core "
    "functional geometry and a small number of high-value details over exhaustive "
    "detail expansion. Once the document visibly represents the requested design "
    "with real native features, capture and inspect the viewport, then report "
    "completion instead of continuing optional refinements."
)


SCENARIOS = {
    "mechanical": (
        "Design a usable complex mechanical bearing carrier bracket for CAD review. "
        "Use your best engineering judgment for load path, mounting flanges, bearing "
        "seat, bolt holes, ribs or bosses, proportions, and native FreeCAD feature "
        "strategy. Create real FreeCAD geometry with native sketch-driven PartDesign "
        "features and include surviving detail features beyond the primary base "
        "solid, such as bearing seats, bolt holes, ribs, bosses, pockets, fillets, "
        "chamfers, or comparable native CAD details chosen by you. Do not report "
        "completion until the model has at least four surviving native PartDesign "
        "features in the feature history, using whatever valid native feature "
        "strategy you judge appropriate. Capture the viewport, inspect what you "
        "made, and keep improving until it is a coherent CAD result rather than "
        "a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "partdesign": (
        "Design a complex parametric PartDesign mounting adapter using sketches and "
        "native PartDesign features. Use pads, pockets, revolves, sweeps, lofts, "
        "patterns, mirror, fillets, chamfers, or other available native features when "
        "appropriate. Capture the viewport, inspect what you made, and keep improving "
        "until it is a coherent CAD result rather than a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "robot": (
        "Design a usable desktop robot arm using NEMA 17 motors. "
        "Use your best engineering judgment for architecture, proportions, "
        "component breakdown, features, and missing dimensions. Create multiple "
        "named component bodies for the base, arm structure, and at least one "
        "joint or end-effector component, then create a native Assembly and add "
        "the generated components. Do not report completion until there are at "
        "least four surviving native PartDesign features across the component "
        "bodies, using whatever valid native feature strategy you judge "
        "appropriate. Capture the viewport, inspect what you made, and keep "
        "improving until it is a coherent CAD result rather than a placeholder. "
        + COMPLETION_DIRECTIVE
    ),
    "drone": (
        "Design a usable quadcopter drone concept. Use your best engineering "
        "judgment for frame architecture, motor layout, battery mounting, "
        "landing support, proportions, and CAD features. Create multiple named "
        "component bodies for the central frame, arms or motor pods, and at "
        "least one battery/landing/support component, then create a native "
        "Assembly and add the generated components. Do not report completion "
        "until there are at least four surviving native PartDesign features "
        "across the component bodies, using whatever valid native feature "
        "strategy you judge appropriate. Capture the viewport, inspect what you "
        "made, and keep improving until it is a coherent CAD result rather than "
        "a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "automotive": (
        "Design a usable automotive suspension control arm or comparable "
        "automotive structural part. Use your best engineering judgment for "
        "load paths, bosses, mounting features, lightening features, proportions, "
        "and manufacturable CAD shape. Create real FreeCAD geometry with native "
        "sketch-driven PartDesign features and include surviving detail features "
        "beyond the primary base solid, such as mount bosses, lightening cutouts, "
        "fillets, chamfers, ribs, or comparable native CAD details chosen by you. "
        "Do not report completion until the model has at least four surviving "
        "native PartDesign features in the feature history, using whatever valid "
        "native feature strategy you judge appropriate. "
        "Capture the viewport, inspect what you made, and keep improving until "
        "it is a coherent CAD result rather than a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "aerospace": (
        "Design a usable aerospace structural part, such as a wing rib or "
        "lightweight bulkhead. Use your best engineering judgment for profile, "
        "spar/fastener/lightening features, stiffness, proportions, and CAD "
        "feature strategy. Create real FreeCAD geometry with native sketch-driven "
        "PartDesign features and include surviving detail features beyond the "
        "primary base solid, such as lightening cutouts, spar/fastener features, "
        "ribs, flanges, fillets, chamfers, or comparable native CAD details chosen "
        "by you. Do not report completion until the model has at least four "
        "surviving native PartDesign features in the feature history, using "
        "whatever valid native feature strategy you judge appropriate. Capture "
        "the viewport, inspect what you made, and keep improving until it is a "
        "coherent CAD result rather than a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "marine": (
        "Design a usable marine mechanical part, such as a propeller shaft "
        "strut or bearing support. Use your best engineering judgment for "
        "flanges, struts, shaft/bearing geometry, mounting features, proportions, "
        "and manufacturable CAD shape. Create real FreeCAD geometry with native "
        "sketch-driven PartDesign features and include surviving detail features "
        "beyond the primary base solid, such as shaft/bearing openings, mounting "
        "flanges, strut reinforcement, holes, fillets, chamfers, ribs, or "
        "comparable native CAD details chosen by you. Do not report completion "
        "until the model has at least four surviving native PartDesign features "
        "in the feature history, using whatever valid native feature strategy you "
        "judge appropriate. Capture the viewport, inspect what you made, and keep "
        "improving until it is a coherent CAD result rather than a placeholder. "
        + COMPLETION_DIRECTIVE
    ),
    "enclosure": (
        "Design a usable complex 3D-printable electronics enclosure with a lid. "
        "Use your best engineering judgment for mounting bosses, ribs, vents, "
        "cable routing, fastener or snap features, wall thickness representation, "
        "and proportions. Create multiple named component bodies for the enclosure "
        "base and lid or cover, include surviving native detail features beyond "
        "the primary base/lid solids, then create a native Assembly and add the "
        "generated components. Do not report completion until the model has at "
        "least five surviving native PartDesign features in the feature history, "
        "using whatever valid native feature strategy you judge appropriate. "
        "Capture the viewport, inspect what you made, and keep improving until "
        "it is a coherent CAD result rather than a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "assembly": (
        "Design a usable multi-part fixture assembly. Use your best engineering "
        "judgment for component breakdown, named parts, positioning, native assembly "
        "structure, fastener/mounting features, and proportions. Create real FreeCAD "
        "geometry, assemble it with native assembly tools when available, capture the "
        "viewport, inspect what you made, and keep improving until it is a coherent "
        "CAD result rather than a placeholder. " + COMPLETION_DIRECTIVE
    ),
    "revision": (
        "Create a compact first-pass 3D-printable electronics mounting bracket "
        "that can be revised in the next prompt. Use your best engineering "
        "judgment for dimensions, sketch strategy, native features, and "
        "proportions, but keep the setup intentionally bounded: a base plate, "
        "mounting bosses or holes, and one stiffening or cable-clearance feature "
        "are enough for the first pass. Create real FreeCAD geometry, capture "
        "and inspect the viewport, then report first-pass completion instead of "
        "expanding optional details. " + COMPLETION_DIRECTIVE
    ),
    "documentation": (
        "Design a documentation-ready CAD part for review and create a native "
        "TechDraw drawing page for it. Use your best engineering judgment for "
        "the part type, proportions, sketch strategy, native PartDesign feature "
        "strategy, and which generated body or feature should appear in the "
        "drawing view. Create real FreeCAD geometry with native sketch-driven "
        "PartDesign features, then switch to TechDrawWorkbench, create a native "
        "TechDraw page, and add at least one native drawing view of the generated "
        "model geometry. Do not report completion until there are at least three "
        "surviving native PartDesign features, at least one TechDraw page, and "
        "at least one TechDraw view with a real model source. Capture the "
        "viewport, inspect what you made, and keep improving until it is a "
        "coherent documented CAD result rather than a placeholder. "
        + COMPLETION_DIRECTIVE
    ),
    "rocket_engine": (
        "Design a usable conceptual liquid rocket engine thrust chamber assembly "
        "for CAD review. Use your best engineering judgment for chamber/nozzle "
        "profile, injector face, bolt pattern, mounting flange, regenerative "
        "cooling jacket representation, feed ports, and proportions. Create real "
        "FreeCAD geometry with native human-equivalent workbench tools. Use "
        "multiple named PartDesign component bodies for major engine structures "
        "such as chamber/nozzle, injector/flange, cooling/feed plumbing, or "
        "mounting hardware as you judge appropriate. Use sketch-driven native "
        "PartDesign features for the main shapes and details, then create a native "
        "Assembly and add the generated components. Do not report completion until "
        "there are at least six surviving native PartDesign features across the "
        "component bodies and the assembly contains at least three generated "
        "components. Capture the viewport, inspect what you made, and keep "
        "improving until it is a coherent complex CAD result rather than a "
        "placeholder. " + COMPLETION_DIRECTIVE
    ),
}

REVISION_PROMPTS = {
    "revision": (
        "Revise the existing bracket you just made. Keep the useful base design, "
        "but improve it for real use by adding at least one meaningful new mounting, "
        "clearance, stiffening, or manufacturability feature. Inspect the existing "
        "document first, modify real FreeCAD objects with native tools, capture and "
        "inspect a fresh viewport screenshot after the change, and report the actual "
        "revision made."
    ),
}


SCENARIO_REQUIREMENTS = {
    "mechanical": {
        "minimum_objects": 8,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 1,
        "minimum_partdesign_features": 4,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "partdesign": {
        "minimum_objects": 3,
        "minimum_mutating_tools": 6,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "robot": {
        "minimum_objects": 10,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 2,
        "minimum_partdesign_features": 4,
        "minimum_assemblies": 1,
        "minimum_assembly_components": 2,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "assembly."),
    },
    "drone": {
        "minimum_objects": 10,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 2,
        "minimum_partdesign_features": 4,
        "minimum_assemblies": 1,
        "minimum_assembly_components": 2,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "assembly."),
    },
    "automotive": {
        "minimum_objects": 8,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 1,
        "minimum_partdesign_features": 4,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "aerospace": {
        "minimum_objects": 8,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 1,
        "minimum_partdesign_features": 4,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "marine": {
        "minimum_objects": 8,
        "minimum_mutating_tools": 12,
        "minimum_partdesign_bodies": 1,
        "minimum_partdesign_features": 4,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "enclosure": {
        "minimum_objects": 12,
        "minimum_mutating_tools": 14,
        "minimum_partdesign_bodies": 2,
        "minimum_partdesign_features": 5,
        "minimum_assemblies": 1,
        "minimum_assembly_components": 2,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "assembly."),
    },
    "assembly": {
        "minimum_objects": 4,
        "minimum_mutating_tools": 8,
        "minimum_assemblies": 1,
        "minimum_assembly_components": 2,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "assembly."),
    },
    "revision": {
        "minimum_objects": 4,
        "minimum_mutating_tools": 10,
        "minimum_revision_mutating_tools": 2,
        "required_tool_prefixes": ("sketcher.", "partdesign."),
    },
    "documentation": {
        "minimum_objects": 8,
        "minimum_mutating_tools": 10,
        "minimum_partdesign_bodies": 1,
        "minimum_partdesign_features": 3,
        "minimum_techdraw_pages": 1,
        "minimum_techdraw_views": 1,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "techdraw."),
    },
    "rocket_engine": {
        "minimum_objects": 16,
        "minimum_mutating_tools": 18,
        "minimum_partdesign_bodies": 3,
        "minimum_partdesign_features": 6,
        "minimum_assemblies": 1,
        "minimum_assembly_components": 3,
        "required_tool_prefixes": ("sketcher.", "partdesign.", "assembly."),
    },
}


def _scenario_prompt() -> tuple[str, str]:
    scenario = (os.environ.get("VIBECAD_ACCEPTANCE_SCENARIO") or "robot").strip().lower()
    prompt = os.environ.get("VIBECAD_ACCEPTANCE_PROMPT")
    if prompt:
        return scenario or "custom", prompt
    if scenario not in SCENARIOS:
        raise ValueError(
            f"Unknown VIBECAD_ACCEPTANCE_SCENARIO={scenario!r}; "
            f"expected one of {sorted(SCENARIOS)} or set VIBECAD_ACCEPTANCE_PROMPT."
        )
    return scenario, SCENARIOS[scenario]


def _optional_float_env(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return float(value)


def _requirements_for_scenario(scenario: str) -> dict[str, object]:
    return {
        "minimum_objects": 1,
        "minimum_mutating_tools": 1,
        "minimum_assemblies": 0,
        "minimum_assembly_components": 0,
        "minimum_partdesign_bodies": 0,
        "minimum_partdesign_features": 0,
        "minimum_techdraw_pages": 0,
        "minimum_techdraw_views": 0,
        "required_tool_prefixes": (),
        **SCENARIO_REQUIREMENTS.get(scenario, {}),
    }


def _partdesign_evidence(partdesign: dict[str, object]) -> dict[str, int]:
    bodies = partdesign.get("bodies", []) if isinstance(partdesign, dict) else []
    if not isinstance(bodies, list):
        bodies = []
    feature_count = 0
    native_feature_count = 0
    for body in bodies:
        if not isinstance(body, dict):
            continue
        features = body.get("features", [])
        if not isinstance(features, list):
            continue
        feature_count += len(features)
        for feature in features:
            if not isinstance(feature, dict):
                continue
            type_id = str(feature.get("type", ""))
            if type_id.startswith("PartDesign::") and type_id not in {
                "PartDesign::Body",
                "PartDesign::CoordinateSystem",
            }:
                native_feature_count += 1
    return {
        "body_count": int(partdesign.get("body_count", 0) or 0) if isinstance(partdesign, dict) else 0,
        "feature_count": feature_count,
        "native_feature_count": native_feature_count,
    }


def _techdraw_evidence(techdraw: dict[str, object]) -> dict[str, int]:
    pages = techdraw.get("pages", []) if isinstance(techdraw, dict) else []
    if not isinstance(pages, list):
        pages = []
    view_count = 0
    sourced_view_count = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        views = page.get("views", [])
        if not isinstance(views, list):
            continue
        view_count += len(views)
        for view in views:
            if isinstance(view, dict) and int(view.get("source_count", 0) or 0) > 0:
                sourced_view_count += 1
    return {
        "page_count": int(techdraw.get("page_count", 0) or 0) if isinstance(techdraw, dict) else 0,
        "view_count": view_count,
        "sourced_view_count": sourced_view_count,
    }


def _transaction_delta_from_result(result: dict[str, object]) -> dict[str, object]:
    delta = result.get("transaction_document_delta") if isinstance(result, dict) else None
    if isinstance(delta, dict):
        return delta
    if isinstance(delta, str):
        try:
            parsed = json.loads(delta)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _deleted_object_names_after(
    tool_trace: list[dict[str, object]],
    start_index: int,
) -> set[str]:
    deleted: set[str] = set()
    for item in tool_trace[start_index + 1 :]:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        delta = _transaction_delta_from_result(result)
        for deleted_item in delta.get("deleted_objects", []) or []:
            if isinstance(deleted_item, dict) and deleted_item.get("name"):
                deleted.add(str(deleted_item["name"]))
    return deleted


def _ineffective_partdesign_features(tool_trace: list[dict[str, object]]) -> list[dict[str, object]]:
    ineffective = []
    for index, item in enumerate(tool_trace):
        tool_name = str(item.get("tool_name") or "")
        if not tool_name.startswith("partdesign."):
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        feature_effect = result.get("feature_effect") if isinstance(result, dict) else None
        if not isinstance(feature_effect, dict) or feature_effect.get("ok"):
            continue
        if result.get("rolled_back_feature"):
            continue
        feature = result.get("active_feature")
        if feature and str(feature) in _deleted_object_names_after(tool_trace, index):
            continue
        ineffective.append(
            {
                "tool_name": tool_name,
                "feature": feature,
                "feature_effect": feature_effect,
            }
        )
    return ineffective


def _latest_request_dump_summary() -> dict[str, object]:
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
        return {
            "exists": True,
            "path": str(latest),
            "file_size": latest.stat().st_size,
            "read_error": str(exc),
        }
    tools = data.get("agent", {}).get("tools", []) if isinstance(data, dict) else []
    tool_names = [
        item.get("function_name")
        for item in tools
        if isinstance(item, dict) and item.get("function_name")
    ] if isinstance(tools, list) else []
    visible_context = data.get("model_visible_context", {}) if isinstance(data, dict) else {}
    proposal_or_queue = [
        name
        for name in tool_names
        if (
            "propose" in str(name)
            or name
            in {
                "core_list_pending_actions",
                "core_apply_action",
                "core_reject_action",
                "core_undo_last_vibecad_action",
                "core_clear_local_session",
            }
        )
    ]
    return {
        "exists": True,
        "path": str(latest),
        "file_size": latest.stat().st_size,
        "schema": data.get("schema") if isinstance(data, dict) else None,
        "model": data.get("model") if isinstance(data, dict) else None,
        "tool_count": len(tools) if isinstance(tools, list) else None,
        "has_model_visible_context": bool(
            isinstance(data, dict) and data.get("model_visible_context")
        ),
        "has_generic_dispatcher": any(
            name in {"execute_vibecad_tool", "core_run_workbench_command"}
            for name in tool_names
        ),
        "has_available_tools": bool(
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
        "proposal_or_queue_functions": proposal_or_queue,
    }


def main() -> int:
    for document in list(App.listDocuments().values()):
        App.closeDocument(document.Name)

    main_window = Gui.getMainWindow()
    main_window.resize(1600, 1000)
    main_window.show()

    service = VibeCADService()
    provider = OpenAIAgentsProvider(
        model=os.environ.get("VIBECAD_ACCEPTANCE_MODEL") or service.provider_model(),
        api_key=service.provider_api_key(),
        reasoning_effort=os.environ.get("VIBECAD_ACCEPTANCE_REASONING_EFFORT")
        or service.provider_reasoning_effort(),
        timeout_seconds=_optional_float_env("VIBECAD_ACCEPTANCE_TURN_TIMEOUT"),
    )
    progress_events = []
    progress_path_text = os.environ.get("VIBECAD_ACCEPTANCE_PROGRESS_PATH")
    progress_path = Path(progress_path_text) if progress_path_text else None
    if progress_path is not None:
        progress_path.write_text("", encoding="utf-8")
    result_path_text = os.environ.get("VIBECAD_ACCEPTANCE_RESULT_PATH")
    result_path = Path(result_path_text) if result_path_text else None

    def write_progress(event):
        line = json.dumps(event, sort_keys=True)
        if progress_path is not None:
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        print(json.dumps({"progress": event}, sort_keys=True), flush=True)

    def report_progress(event):
        progress_events.append(event)
        write_progress(event)

    write_progress({"event": "acceptance_script_started"})
    scenario, prompt = _scenario_prompt()
    response = run_prompt(
        prompt,
        service=service,
        provider=provider,
        progress_callback=report_progress,
        max_provider_seconds=_optional_float_env("VIBECAD_ACCEPTANCE_TOTAL_TIMEOUT"),
    )
    responses = [response]
    revision_prompt = REVISION_PROMPTS.get(scenario)
    revision_response = None
    if revision_prompt:
        write_progress({"event": "revision_prompt_started"})
        revision_response = run_prompt(
            revision_prompt,
            service=service,
            provider=provider,
            progress_callback=report_progress,
            max_provider_seconds=_optional_float_env("VIBECAD_ACCEPTANCE_TOTAL_TIMEOUT"),
        )
        responses.append(revision_response)
    assembly = service.assembly_summary()
    partdesign = service.partdesign_summary()
    partdesign_evidence = _partdesign_evidence(partdesign)
    techdraw = service.techdraw_summary()
    techdraw_evidence = _techdraw_evidence(techdraw)
    document = service.document_summary()
    screenshot = service.view_screenshot_summary()
    assembly_components = 0
    if assembly.get("assemblies"):
        assembly_components = assembly["assemblies"][0].get("components", 0)
    combined_tool_trace = [
        item
        for item_response in responses
        for item in item_response.tool_trace
    ]
    provider_timeout_events = [
        item
        for item in progress_events
        if isinstance(item, dict) and item.get("event") == "provider_total_timeout"
    ]
    tool_names = [item.get("tool_name") for item in combined_tool_trace]
    mutating_tools = [
        item.get("tool_name")
        for item in combined_tool_trace
        if item.get("ok") and str(item.get("safety", "")).endswith("write")
    ]
    ineffective_partdesign_features = _ineffective_partdesign_features(combined_tool_trace)
    revision_mutating_tools = (
        [
            item.get("tool_name")
            for item in revision_response.tool_trace
            if item.get("ok") and str(item.get("safety", "")).endswith("write")
        ]
        if revision_response is not None
        else []
    )
    report = service.tool_shape_report()
    recent_gaps = report.get("recent_tool_shape_feedback", [])
    requirements = _requirements_for_scenario(scenario)
    required_prefixes = tuple(requirements.get("required_tool_prefixes", ()))
    required_prefix_hits = {
        prefix: any(str(name or "").startswith(prefix) for name in mutating_tools)
        for prefix in required_prefixes
    }
    request_dump = _latest_request_dump_summary()
    failures = []
    for index, item_response in enumerate(responses, start=1):
        if item_response.provider != "OpenAIAgentsProvider":
            failures.append(
                f"turn {index} provider was {item_response.provider!r}, expected OpenAIAgentsProvider"
            )
        if item_response.error:
            failures.append(f"turn {index} provider error: {item_response.error}")
    final_output = (responses[-1].final_output or "").strip()
    final_output_lower = final_output.lower()
    if not final_output:
        failures.append("final output was empty")
    elif _last_checkpoint_index(final_output_lower) > _last_completion_index(final_output_lower):
        failures.append("final output stopped at a checkpoint instead of completion")
    unresolved_reasons = _final_output_unresolved_reasons(final_output_lower)
    if unresolved_reasons:
        failures.append(
            "final output described unresolved or ineffective CAD work: "
            f"{unresolved_reasons}"
        )
    if document.get("object_count", 0) < int(requirements["minimum_objects"]):
        failures.append(
            f"object count {document.get('object_count', 0)} below required {requirements['minimum_objects']}"
        )
    if len(mutating_tools) < int(requirements["minimum_mutating_tools"]):
        failures.append(
            f"mutating tool count {len(mutating_tools)} below required {requirements['minimum_mutating_tools']}"
        )
    minimum_revision_mutating = int(requirements.get("minimum_revision_mutating_tools", 0) or 0)
    if len(revision_mutating_tools) < minimum_revision_mutating:
        failures.append(
            "revision mutating tool count "
            f"{len(revision_mutating_tools)} below required {minimum_revision_mutating}"
        )
    missing_prefixes = [
        prefix for prefix, hit in required_prefix_hits.items()
        if not hit
    ]
    if missing_prefixes:
        failures.append(f"missing required mutating tool prefixes: {missing_prefixes}")
    if ineffective_partdesign_features:
        failures.append(
            "PartDesign feature tools reported ineffective geometry changes: "
            f"{ineffective_partdesign_features}"
        )
    if provider_timeout_events:
        failures.append(
            "provider loop timed out before verified completion: "
            f"{provider_timeout_events}"
        )
    if assembly.get("assembly_count", 0) < int(requirements["minimum_assemblies"]):
        failures.append(
            f"assembly count {assembly.get('assembly_count', 0)} below required {requirements['minimum_assemblies']}"
        )
    if assembly_components < int(requirements["minimum_assembly_components"]):
        failures.append(
            f"assembly component count {assembly_components} below required {requirements['minimum_assembly_components']}"
        )
    if partdesign_evidence["body_count"] < int(requirements["minimum_partdesign_bodies"]):
        failures.append(
            "PartDesign body count "
            f"{partdesign_evidence['body_count']} below required {requirements['minimum_partdesign_bodies']}"
        )
    if partdesign_evidence["native_feature_count"] < int(requirements["minimum_partdesign_features"]):
        failures.append(
            "PartDesign native feature count "
            f"{partdesign_evidence['native_feature_count']} below required {requirements['minimum_partdesign_features']}"
        )
    if techdraw_evidence["page_count"] < int(requirements["minimum_techdraw_pages"]):
        failures.append(
            "TechDraw page count "
            f"{techdraw_evidence['page_count']} below required {requirements['minimum_techdraw_pages']}"
        )
    if techdraw_evidence["sourced_view_count"] < int(requirements["minimum_techdraw_views"]):
        failures.append(
            "TechDraw sourced view count "
            f"{techdraw_evidence['sourced_view_count']} below required {requirements['minimum_techdraw_views']}"
        )
    if not bool(screenshot.get("captured")):
        failures.append("viewport screenshot was not captured")
    elif screenshot.get("file_size", 0) <= 1000:
        failures.append(f"screenshot file too small: {screenshot.get('file_size', 0)}")
    if recent_gaps:
        failures.append("model reported tool-shape gaps during the run")
    if not request_dump.get("exists"):
        failures.append("OpenAI request dump was not written")
    elif request_dump.get("schema") != "vibecad-openai-agents-request-v1":
        failures.append(f"OpenAI request dump schema mismatch: {request_dump.get('schema')}")
    else:
        if request_dump.get("has_generic_dispatcher"):
            failures.append("OpenAI request dump included generic dispatcher tool")
        if request_dump.get("has_available_tools"):
            failures.append("OpenAI request dump leaked available_tools into model-visible context")
        if request_dump.get("has_tool_menu_context"):
            failures.append("OpenAI request dump leaked provider tool menus into model-visible context")
        if request_dump.get("proposal_or_queue_functions"):
            failures.append(
                "OpenAI request dump included proposal/queue functions: "
                f"{request_dump.get('proposal_or_queue_functions')}"
            )

    result = {
        "scenario": scenario,
        "prompt": prompt,
        "revision_prompt": revision_prompt,
        "provider": responses[-1].provider,
        "final_output": responses[-1].final_output,
        "turn_count": len(responses),
        "tool_count": len(combined_tool_trace),
        "tools": tool_names,
        "mutating_tool_count": len(mutating_tools),
        "mutating_tools": mutating_tools,
        "revision_mutating_tool_count": len(revision_mutating_tools),
        "revision_mutating_tools": revision_mutating_tools,
        "ineffective_partdesign_features": ineffective_partdesign_features,
        "recent_tool_shape_feedback": recent_gaps,
        "progress_event_count": len(progress_events),
        "progress_events": [item.get("event") for item in progress_events],
        "provider_timeout_event_count": len(provider_timeout_events),
        "provider_timeout_events": provider_timeout_events,
        "object_count": document.get("object_count"),
        "partdesign_body_count": partdesign_evidence["body_count"],
        "partdesign_feature_count": partdesign_evidence["feature_count"],
        "partdesign_native_feature_count": partdesign_evidence["native_feature_count"],
        "assembly_count": assembly.get("assembly_count"),
        "assembly_components": assembly_components,
        "techdraw_page_count": techdraw_evidence["page_count"],
        "techdraw_view_count": techdraw_evidence["view_count"],
        "techdraw_sourced_view_count": techdraw_evidence["sourced_view_count"],
        "screenshot_captured": bool(screenshot.get("captured")),
        "screenshot_file_size": screenshot.get("file_size", 0),
        "requirements": requirements,
        "required_prefix_hits": required_prefix_hits,
        "request_dump": request_dump,
        "failures": failures,
    }
    result["ok"] = not failures
    if result_path is not None:
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def run_and_exit() -> None:
    try:
        code = main()
    except Exception:
        result = {"ok": False, "traceback": traceback.format_exc()}
        result_path_text = os.environ.get("VIBECAD_ACCEPTANCE_RESULT_PATH")
        if result_path_text:
            Path(result_path_text).write_text(
                json.dumps(result, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        print(json.dumps(result, indent=2))
        code = 1
    try:
        from PySide import QtWidgets

        app = QtWidgets.QApplication.instance()
    except Exception:
        app = None
    if app is not None:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(code)
        return
    sys.exit(code)


if __name__ in {"__main__", "__builtin__", "builtins", "vibecad_live_provider_acceptance"}:
    try:
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, run_and_exit)
    except Exception:
        run_and_exit()
else:
    _write_boot_event(f"boot_not_main:{__name__}")
