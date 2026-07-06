#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Run VibeCAD runtime GUI audits as a repeatable battery.

This intentionally runs each audit in a fresh FreeCAD process. A stuck dialog,
crash, or event-loop hang should fail one named audit without hiding which
coverage path broke.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREECAD_RUNNER = REPO_ROOT / "tools" / "freecad_venv.sh"


@dataclass(frozen=True)
class Audit:
    name: str
    args: tuple[str, ...]
    description: str


DEFAULT_AUDITS = (
    Audit(
        name="dock_panel",
        args=("tools/vibecad_panel_dock_audit.py",),
        description="assistant opens as a normal right-side dock panel",
    ),
    Audit(
        name="panel_part_workbench",
        args=(
            "tools/vibecad_assistant_panel_runtime_audit.py",
            "--pass",
            "--workbench",
            "PartWorkbench",
        ),
        description="assistant exposes contextual UI/tools in the Part workbench",
    ),
    Audit(
        name="panel_partdesign_workbench",
        args=(
            "tools/vibecad_assistant_panel_runtime_audit.py",
            "--pass",
            "--workbench",
            "PartDesignWorkbench",
        ),
        description="assistant exposes contextual UI/tools in the Part Design workbench",
    ),
    Audit(
        name="panel_assembly_workbench",
        args=(
            "tools/vibecad_assistant_panel_runtime_audit.py",
            "--pass",
            "--workbench",
            "AssemblyWorkbench",
        ),
        description="assistant exposes contextual UI/tools in the Assembly workbench",
    ),
    Audit(
        name="open_modify_existing_model",
        args=("tools/vibecad_open_modify_runtime_audit.py",),
        description="tool loop can open an existing FCStd file, edit it, and screenshot it",
    ),
)

LIVE_AUDITS = (
    Audit(
        name="live_provider_acceptance",
        args=("tools/vibecad_live_provider_acceptance.py",),
        description="real provider loop using configured OpenAI credentials",
    ),
)


def tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def extract_json_payload(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and not text[index + end :].strip():
            return payload
    return None


def command_for(audit: Audit, timeout_seconds: int) -> list[str]:
    return [
        "timeout",
        str(timeout_seconds),
        "xvfb-run",
        "-a",
        str(FREECAD_RUNNER),
        *audit.args,
    ]


def run_audit(audit: Audit, timeout_seconds: int, output_chars: int) -> dict:
    command = command_for(audit, timeout_seconds)
    started = time.monotonic()
    print(f"RUN {audit.name}: {audit.description}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        duration = time.monotonic() - started
        stdout_tail = tail(completed.stdout, output_chars)
        stderr_tail = tail(completed.stderr, output_chars)
        payload = extract_json_payload(completed.stdout)
        payload_ok = payload.get("ok") if isinstance(payload, dict) else None
        ok = completed.returncode == 0 and payload_ok is not False
        result = {
            "name": audit.name,
            "description": audit.description,
            "ok": ok,
            "returncode": completed.returncode,
            "duration_seconds": round(duration, 3),
            "command": command,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }
        if payload_ok is not None:
            result["payload_ok"] = bool(payload_ok)
        if completed.returncode == 0 and payload_ok is False:
            result["error"] = "audit JSON payload reported ok=false"
    except Exception as exc:
        duration = time.monotonic() - started
        result = {
            "name": audit.name,
            "description": audit.description,
            "ok": False,
            "returncode": None,
            "duration_seconds": round(duration, 3),
            "command": command,
            "error": repr(exc),
            "stdout_tail": "",
            "stderr_tail": "",
        }
    status = "PASS" if result["ok"] else "FAIL"
    print(f"{status} {audit.name} ({result['duration_seconds']}s)", flush=True)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Per-audit timeout in seconds.",
    )
    parser.add_argument(
        "--output-chars",
        type=int,
        default=8000,
        help="Characters of stdout/stderr tail retained per audit.",
    )
    parser.add_argument(
        "--include-live-provider",
        action="store_true",
        help="Also run network/key-dependent live provider acceptance.",
    )
    parser.add_argument(
        "--audit",
        action="append",
        help="Run only this audit name. May be passed more than once.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    audits = list(DEFAULT_AUDITS)
    if args.include_live_provider:
        audits.extend(LIVE_AUDITS)
    if args.audit:
        requested = set(args.audit)
        audits = [audit for audit in audits if audit.name in requested]
        missing = sorted(requested.difference({audit.name for audit in audits}))
        if missing:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "unknown audits requested",
                        "missing": missing,
                        "available": [audit.name for audit in DEFAULT_AUDITS + LIVE_AUDITS],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2

    results = [
        run_audit(audit, args.timeout, args.output_chars)
        for audit in audits
    ]
    failures = [result for result in results if not result["ok"]]
    summary = {
        "ok": not failures,
        "audit_count": len(results),
        "failure_count": len(failures),
        "coverage": [
            {
                "name": audit.name,
                "description": audit.description,
                "live_provider": audit in LIVE_AUDITS,
            }
            for audit in audits
        ],
        "results": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
