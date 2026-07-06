#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run real OpenAI-backed VibeCAD acceptance scenarios and summarize evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


DEFAULT_SCENARIOS = (
    "mechanical",
    "partdesign",
    "robot",
    "drone",
    "automotive",
    "aerospace",
    "marine",
    "enclosure",
    "assembly",
    "revision",
    "documentation",
    "rocket_engine",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "read_error": str(exc), "path": str(path)}


def _request_dump_summary(request_dump_dir: Path) -> dict:
    latest = request_dump_dir / "latest-openai-request.json"
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


def _partial_result_from_progress(
    scenario: str,
    progress_path: Path,
    request_dump_dir: Path,
    failure: str,
) -> dict:
    tools = []
    mutating_tools = []
    object_count = None
    screenshot_captured = False
    if progress_path.is_file():
        for raw_line in progress_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw_line)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "tool_call_completed":
                tool_name = event.get("tool_name")
                if tool_name:
                    tools.append(tool_name)
                if event.get("ok") and str(event.get("safety", "")).endswith("write"):
                    mutating_tools.append(tool_name)
                if tool_name == "core.capture_view_screenshot" and event.get("ok"):
                    screenshot_captured = True
            delta = event.get("document_delta")
            if isinstance(delta, dict) and "after_object_count" in delta:
                object_count = delta.get("after_object_count")
            result = event.get("result")
            if isinstance(result, dict):
                transaction_delta = result.get("transaction_document_delta")
                if isinstance(transaction_delta, dict) and "object_count_after" in transaction_delta:
                    object_count = transaction_delta.get("object_count_after")
    return {
        "ok": False,
        "scenario": scenario,
        "provider": "OpenAIAgentsProvider" if tools else None,
        "tool_count": len(tools),
        "tools": tools,
        "mutating_tool_count": len(mutating_tools),
        "mutating_tools": mutating_tools,
        "object_count": object_count,
        "screenshot_captured": screenshot_captured,
        "request_dump": _request_dump_summary(request_dump_dir),
        "failures": [failure],
        "partial_evidence": True,
    }


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _scenario_summary(scenario: str, result: dict, elapsed_seconds: float, exit_code: int) -> dict:
    request_dump = result.get("request_dump", {}) if isinstance(result, dict) else {}
    return {
        "scenario": scenario,
        "ok": bool(result.get("ok")) and exit_code == 0,
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "provider": result.get("provider"),
        "object_count": result.get("object_count"),
        "partdesign_body_count": result.get("partdesign_body_count"),
        "partdesign_feature_count": result.get("partdesign_feature_count"),
        "partdesign_native_feature_count": result.get("partdesign_native_feature_count"),
        "assembly_count": result.get("assembly_count"),
        "assembly_components": result.get("assembly_components"),
        "techdraw_page_count": result.get("techdraw_page_count"),
        "techdraw_view_count": result.get("techdraw_view_count"),
        "techdraw_sourced_view_count": result.get("techdraw_sourced_view_count"),
        "tool_count": result.get("tool_count"),
        "mutating_tool_count": result.get("mutating_tool_count"),
        "screenshot_captured": result.get("screenshot_captured"),
        "screenshot_file_size": result.get("screenshot_file_size"),
        "provider_timeout_event_count": result.get("provider_timeout_event_count"),
        "request_dump_exists": request_dump.get("exists"),
        "request_dump_schema": request_dump.get("schema"),
        "request_dump_tool_count": request_dump.get("tool_count"),
        "request_dump_has_generic_dispatcher": request_dump.get("has_generic_dispatcher"),
        "request_dump_has_available_tools": request_dump.get("has_available_tools"),
        "request_dump_has_tool_menu_context": request_dump.get("has_tool_menu_context"),
        "request_dump_proposal_or_queue_functions": request_dump.get("proposal_or_queue_functions"),
        "failures": result.get("failures", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenarios",
        nargs="*",
        default=list(DEFAULT_SCENARIOS),
        help="Scenario names to run. Defaults to the core complex CAD matrix.",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp/vibecad-live-acceptance-matrix",
        help="Directory for per-scenario result, progress, request dumps, and summary files.",
    )
    parser.add_argument(
        "--total-timeout",
        type=float,
        default=600.0,
        help="Autonomous provider loop timeout per scenario, in seconds.",
    )
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=0.0,
        help="OpenAI provider turn timeout per scenario, in seconds. Use 0 for no provider-turn timeout.",
    )
    parser.add_argument(
        "--process-timeout",
        type=float,
        default=720.0,
        help="Outer process timeout per scenario, in seconds.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("VIBECAD_ACCEPTANCE_MODEL", ""),
        help="Optional model override passed to the live acceptance script.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=os.environ.get("VIBECAD_ACCEPTANCE_REASONING_EFFORT", ""),
        help="Optional reasoning effort override passed to the live acceptance script.",
    )
    args = parser.parse_args()

    repo = _repo_root()
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []

    for scenario in args.scenarios:
        scenario_dir = output_dir / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        result_path = scenario_dir / "result.json"
        progress_path = scenario_dir / "progress.jsonl"
        request_dump_dir = scenario_dir / "request-dumps"
        request_dump_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "VIBECAD_ACCEPTANCE_SCENARIO": scenario,
                "VIBECAD_ACCEPTANCE_TOTAL_TIMEOUT": str(args.total_timeout),
                "VIBECAD_ACCEPTANCE_TURN_TIMEOUT": str(args.turn_timeout),
                "VIBECAD_ACCEPTANCE_RESULT_PATH": str(result_path),
                "VIBECAD_ACCEPTANCE_PROGRESS_PATH": str(progress_path),
                "VIBECAD_OPENAI_REQUEST_DUMP_DIR": str(request_dump_dir),
            }
        )
        if args.model:
            env["VIBECAD_ACCEPTANCE_MODEL"] = args.model
        if args.reasoning_effort:
            env["VIBECAD_ACCEPTANCE_REASONING_EFFORT"] = args.reasoning_effort

        command = [
            "xvfb-run",
            "-a",
            "tools/freecad_venv.sh",
            "tools/vibecad_live_provider_acceptance.py",
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=args.process_timeout,
                check=False,
            )
            exit_code = completed.returncode
            (scenario_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
            (scenario_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            (scenario_dir / "stdout.txt").write_text(_timeout_text(exc.stdout), encoding="utf-8")
            (scenario_dir / "stderr.txt").write_text(_timeout_text(exc.stderr), encoding="utf-8")
            partial = _partial_result_from_progress(
                scenario,
                progress_path,
                request_dump_dir,
                f"matrix process timeout after {args.process_timeout:g} seconds",
            )
            result_path.write_text(
                json.dumps(partial, indent=2, sort_keys=True),
                encoding="utf-8",
            )

        elapsed = time.monotonic() - started
        result = _load_json(result_path)
        summary = _scenario_summary(scenario, result, elapsed, exit_code)
        summaries.append(summary)
        print(json.dumps(summary, sort_keys=True), flush=True)

    matrix = {
        "ok": all(item["ok"] for item in summaries),
        "scenario_count": len(summaries),
        "passed": [item["scenario"] for item in summaries if item["ok"]],
        "failed": [item["scenario"] for item in summaries if not item["ok"]],
        "summaries": summaries,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(matrix, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(matrix, indent=2, sort_keys=True))
    return 0 if matrix["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
