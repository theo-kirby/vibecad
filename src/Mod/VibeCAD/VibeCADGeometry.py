# SPDX-License-Identifier: LGPL-2.1-or-later

"""Process-isolated native geometry execution for VibeCAD."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable


DEFAULT_DEADLINE_SECONDS = 30.0


def worker_executable() -> Path:
    import FreeCAD as App

    bin_root = Path(str(App.getHomePath())) / "bin"
    names = (
        ("VibeCADGeometryWorker.exe", "vibecadgeometryworker.exe")
        if sys.platform == "win32"
        else ("VibeCADGeometryWorker", "vibecadgeometryworker")
    )
    for name in names:
        candidate = bin_root / name
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"The VibeCAD geometry worker is missing from {bin_root}. Rebuild or reinstall VibeCAD."
    )


def execute_job(
    request_path: str | Path,
    result_path: str | Path,
    *,
    cancellation_check: Callable[[], bool] | None = None,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> dict[str, Any]:
    executable = worker_executable()
    creation_flags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if sys.platform == "win32"
        else 0
    )
    started = time.monotonic()
    process = subprocess.Popen(
        [str(executable), str(Path(request_path))],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
        creationflags=creation_flags,
    )
    cancelled = False
    timed_out = False
    deadline = started + max(0.1, float(deadline_seconds)) + 2.0
    while process.poll() is None:
        if cancellation_check is not None and cancellation_check():
            cancelled = True
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.05)
    if cancelled or timed_out:
        _terminate_process(process)
    stdout, stderr = process.communicate()
    elapsed = round(time.monotonic() - started, 6)
    if cancelled:
        return {
            "ok": False,
            "failure_code": "RUN_CANCELLED",
            "failure_stage": "external_process",
            "error": "The isolated geometry operation was stopped by the user.",
            "elapsed_seconds": elapsed,
        }
    if timed_out:
        return {
            "ok": False,
            "failure_code": "GEOMETRY_DEADLINE_EXCEEDED",
            "failure_stage": "external_process",
            "error": f"The isolated geometry operation exceeded {deadline_seconds:.1f} seconds.",
            "elapsed_seconds": elapsed,
        }
    result_file = Path(result_path)
    if not result_file.is_file():
        return {
            "ok": False,
            "failure_code": "GEOMETRY_WORKER_NO_RESULT",
            "failure_stage": "external_process",
            "error": "The isolated geometry worker exited without a result.",
            "worker": {
                "returncode": process.returncode,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
            },
            "elapsed_seconds": elapsed,
        }
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "failure_code": "GEOMETRY_WORKER_RESULT_INVALID",
            "failure_stage": "external_process",
            "error": f"The isolated geometry worker returned invalid JSON: {exc}",
            "elapsed_seconds": elapsed,
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "failure_code": "GEOMETRY_WORKER_RESULT_INVALID",
            "failure_stage": "external_process",
            "error": "The isolated geometry worker result is not an object.",
            "elapsed_seconds": elapsed,
        }
    result.setdefault("elapsed_seconds", elapsed)
    if process.returncode != 0 and result.get("ok"):
        result.update(
            {
                "ok": False,
                "failure_code": "GEOMETRY_WORKER_EXITED",
                "failure_stage": "external_process",
                "error": f"The isolated geometry worker exited with code {process.returncode}.",
            }
        )
    return result


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1.5)
    except Exception:
        try:
            if sys.platform == "win32":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            pass
