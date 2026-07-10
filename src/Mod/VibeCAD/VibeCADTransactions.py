# SPDX-License-Identifier: LGPL-2.1-or-later

"""Transaction helpers for VibeCAD write tools."""

from __future__ import annotations

from typing import Any, Callable


ActionHandler = Callable[[], dict[str, Any]]
VerificationHandler = Callable[[dict[str, Any]], dict[str, Any]]


def run_freecad_transaction(
    name: str,
    handler: ActionHandler,
    verifier: VerificationHandler | None = None,
) -> dict[str, Any]:
    """Run one native FreeCAD undo transaction without rollback or cleanup.

    Failure is retained in the document exactly as FreeCAD produced it so the
    model and user can inspect and repair the real feature history.
    """
    try:
        import FreeCAD as App
    except Exception as exc:
        return {"ok": False, "error": f"FreeCAD unavailable: {exc}"}

    doc = App.ActiveDocument
    before = _document_snapshot(doc)
    report_view_error_summary()
    result: dict[str, Any] = {}
    operation_error: str | None = None
    recompute_error: str | None = None
    commit_error: str | None = None
    verification: dict[str, Any] = {"ok": True, "checks": []}
    opened = False
    try:
        if doc is not None and hasattr(doc, "openTransaction"):
            doc.openTransaction(name)
            opened = True
        try:
            raw_result = handler()
            result = raw_result if isinstance(raw_result, dict) else {"value": raw_result}
        except Exception as exc:
            operation_error = str(exc)
        active_doc = App.ActiveDocument or doc
        if active_doc is not None and hasattr(active_doc, "recompute"):
            try:
                active_doc.recompute()
            except Exception as exc:
                recompute_error = str(exc)
        if operation_error or recompute_error:
            verification = {
                "ok": False,
                "checks": [
                    {
                        "ok": False,
                        "name": "operation",
                        "message": operation_error or recompute_error,
                    }
                ],
            }
        elif verifier is not None:
            try:
                verification = verifier(result)
            except Exception as exc:
                verification = {"ok": False, "error": str(exc), "checks": []}
        report_view_errors = report_view_error_summary()
        report_error = _report_view_transaction_error(report_view_errors)
        if report_error:
            verification = dict(verification)
            verification["ok"] = False
            checks = list(verification.get("checks", []) or [])
            checks.append(
                {
                    "ok": False,
                    "name": "report_view_errors",
                    "message": report_error,
                }
            )
            verification["checks"] = checks
        if opened and doc is not None and hasattr(doc, "commitTransaction"):
            try:
                doc.commitTransaction()
            except Exception as exc:
                commit_error = str(exc)
            opened = False
        active_doc = App.ActiveDocument or doc
        after = _document_snapshot(active_doc)
        document_delta = _document_delta(before, after)
        transaction_ok = (
            not operation_error
            and not recompute_error
            and bool(verification.get("ok", True))
            and not bool(report_error)
            and not commit_error
        )
        transaction: dict[str, Any] = {
            "ok": transaction_ok,
            "result": result,
            "verification": verification,
            "document_delta": document_delta,
            "report_view_errors": report_view_errors,
            "transaction_name": name,
            "committed_transaction": bool(doc is not None and not commit_error),
        }
        if not transaction_ok:
            if operation_error:
                transaction["error"] = operation_error
            elif recompute_error:
                transaction["error"] = recompute_error
            elif report_error:
                transaction["error"] = report_error
            elif commit_error:
                transaction["error"] = commit_error
            elif verification.get("error"):
                transaction["error"] = str(verification.get("error"))
            else:
                transaction["error"] = "FreeCAD transaction verification failed."
            if commit_error:
                transaction["commit_error"] = commit_error
            if recompute_error:
                transaction["recompute_error"] = recompute_error
        return transaction
    except Exception as exc:
        emergency_commit_error = None
        if opened and doc is not None and hasattr(doc, "commitTransaction"):
            try:
                doc.commitTransaction()
            except Exception as commit_exc:
                emergency_commit_error = str(commit_exc)
        transaction = {
            "ok": False,
            "error": str(exc),
            "result": result,
            "document_delta": _document_delta(
                before,
                _document_snapshot(App.ActiveDocument or doc),
            ),
            "report_view_errors": report_view_error_summary(),
            "transaction_name": name,
        }
        if emergency_commit_error:
            transaction["commit_error"] = emergency_commit_error
        return transaction


def _document_snapshot(doc: Any | None) -> dict[str, Any]:
    if doc is None:
        return {"document": None, "object_count": 0, "objects": []}
    objects = []
    for obj in getattr(doc, "Objects", []):
        item = {
            "name": getattr(obj, "Name", ""),
            "label": getattr(obj, "Label", getattr(obj, "Name", "")),
            "type": getattr(obj, "TypeId", ""),
        }
        shape = _shape_summary(obj)
        if shape.get("available") and _should_include_shape_in_snapshot(obj, shape):
            item["shape"] = shape
        objects.append(item)
    return {
        "document": getattr(doc, "Name", None),
        "object_count": len(objects),
        "objects": objects,
    }


def _should_include_shape_in_snapshot(obj: Any, shape: dict[str, Any]) -> bool:
    type_id = str(getattr(obj, "TypeId", ""))
    if type_id.startswith("App::"):
        return False
    return (
        type_id.startswith("Part::")
        or type_id.startswith("PartDesign::")
        or type_id.startswith("Sketcher::")
        or int(shape.get("solids", 0) or 0) > 0
        or abs(float(shape.get("volume", 0.0) or 0.0)) > 1e-9
    )


def _shape_summary(obj: Any) -> dict[str, Any]:
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return {"available": False}
    try:
        summary = {
            "available": True,
            "solids": len(getattr(shape, "Solids", []) or []),
            "faces": len(getattr(shape, "Faces", []) or []),
            "edges": len(getattr(shape, "Edges", []) or []),
            "vertices": len(getattr(shape, "Vertexes", []) or []),
            "volume": float(getattr(shape, "Volume", 0.0) or 0.0),
        }
        bound_box = _bound_box_summary(getattr(shape, "BoundBox", None))
        if bound_box:
            summary["bound_box"] = bound_box
        return summary
    except Exception:
        return {"available": False}


def _bound_box_summary(bound_box: Any) -> dict[str, Any] | None:
    if bound_box is None:
        return None
    try:
        return {
            "xmin": float(bound_box.XMin),
            "ymin": float(bound_box.YMin),
            "zmin": float(bound_box.ZMin),
            "xmax": float(bound_box.XMax),
            "ymax": float(bound_box.YMax),
            "zmax": float(bound_box.ZMax),
            "xlength": float(bound_box.XLength),
            "ylength": float(bound_box.YLength),
            "zlength": float(bound_box.ZLength),
        }
    except Exception:
        return None


def _document_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_objects = {item["name"]: item for item in before.get("objects", [])}
    after_objects = {item["name"]: item for item in after.get("objects", [])}
    before_names = set(before_objects)
    after_names = set(after_objects)
    changed = []
    for name in sorted(before_names.intersection(after_names)):
        before_item = before_objects[name]
        after_item = after_objects[name]
        if before_item != after_item:
            changed.append({"name": name, "before": before_item, "after": after_item})
    return {
        "object_count_before": int(before.get("object_count", 0)),
        "object_count_after": int(after.get("object_count", 0)),
        "object_count_delta": int(after.get("object_count", 0)) - int(before.get("object_count", 0)),
        "created_objects": [after_objects[name] for name in sorted(after_names - before_names)],
        "deleted_objects": [before_objects[name] for name in sorted(before_names - after_names)],
        "changed_objects": changed,
    }


_REPORT_VIEW_CURSORS: dict[str, int] = {}


def report_view_error_summary(include_stale: bool = False) -> dict[str, Any]:
    """Summarize report-view error lines, returning only errors new since the last call.

    A per-widget cursor remembers how many lines have already been seen, so errors
    from earlier operations are not re-reported after later, successful ones.
    Multi-line Python tracebacks are grouped into a single block (header, frames,
    and exception message). Pass ``include_stale=True`` to also return previously
    seen errors.
    """
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets
    except Exception as exc:
        return {
            "captured": False,
            "errors": [],
            "stale_error_count": 0,
            "source": "unavailable",
            "reason": str(exc),
        }

    try:
        main_window = Gui.getMainWindow()
        candidates = main_window.findChildren(QtWidgets.QPlainTextEdit)
        candidates += main_window.findChildren(QtWidgets.QTextEdit)
        new_blocks: list[str] = []
        stale_blocks: list[str] = []
        for widget in candidates:
            object_name = getattr(widget, "objectName", lambda: "")()
            window_title = getattr(widget, "windowTitle", lambda: "")()
            identity = f"{object_name} {window_title} {widget.__class__.__name__}".lower()
            if "report" not in identity:
                continue
            text = widget.toPlainText() if hasattr(widget, "toPlainText") else widget.toHtml()
            all_lines = text.splitlines()
            key = f"{widget.__class__.__name__}:{object_name}:{window_title}"
            cursor = _REPORT_VIEW_CURSORS.get(key, 0)
            if cursor > len(all_lines):
                cursor = 0
            for start_index, block in _extract_error_blocks(all_lines):
                if start_index >= cursor:
                    new_blocks.append(block)
                else:
                    stale_blocks.append(block)
            _REPORT_VIEW_CURSORS[key] = len(all_lines)
        errors = (stale_blocks + new_blocks) if include_stale else new_blocks
        return {
            "captured": True,
            "errors": errors[-20:],
            "stale_error_count": len(stale_blocks),
            "source": "report_view_widgets",
        }
    except Exception as exc:
        return {
            "captured": False,
            "errors": [],
            "stale_error_count": 0,
            "source": "report_view_widgets",
            "reason": str(exc),
        }


def _extract_error_blocks(lines: list[str]) -> list[tuple[int, str]]:
    """Extract error entries as ``(start_line_index, text)`` pairs.

    Python tracebacks are captured as one multi-line block: the
    ``Traceback (most recent call last):`` header, the indented frame/code
    lines that follow, and the trailing exception message line.
    """
    blocks: list[tuple[int, str]] = []
    index = 0
    total = len(lines)
    while index < total:
        stripped = lines[index].strip()
        if stripped.lower().startswith("traceback (most recent call last"):
            start = index
            block_lines = [stripped]
            index += 1
            while index < total and lines[index].strip() and lines[index][:1] in (" ", "\t"):
                block_lines.append(lines[index].rstrip())
                index += 1
            if index < total and lines[index].strip():
                block_lines.append(lines[index].strip())
                index += 1
            blocks.append((start, _bounded_report_view_line("\n".join(block_lines), 2000)))
            continue
        if _is_report_view_error_line(stripped):
            blocks.append((index, _bounded_report_view_line(stripped)))
        index += 1
    return blocks


def _is_report_view_error_line(line: str) -> bool:
    lowered = line.lower()
    if not line:
        return False
    if lowered == "no report-view errors detected.":
        return False
    if '{"progress":' in line or '"event": "tool_call_completed"' in line:
        return False
    if lowered.startswith("report errors:"):
        return False
    fatal_phrases = (
        "failed to make face",
        "invalid edge link",
        "command not done",
        "brep_api",
        "part::facemaker: result shape is null",
    )
    return (
        "error" in lowered
        or "exception" in lowered
        or "traceback" in lowered
        or any(phrase in lowered for phrase in fatal_phrases)
    )


def _bounded_report_view_line(line: str, limit: int = 500) -> str:
    if len(line) <= limit:
        return line
    return line[: limit - 3] + "..."


def _report_view_transaction_error(report_view_errors: dict[str, Any]) -> str | None:
    if not isinstance(report_view_errors, dict):
        return None
    errors = [str(item) for item in report_view_errors.get("errors", []) or []]
    if not errors:
        return None
    first = errors[0]
    if len(first) > 220:
        first = first[:217] + "..."
    if len(errors) == 1:
        return f"FreeCAD reported an error during this operation: {first}"
    return (
        f"FreeCAD reported {len(errors)} errors during this operation. "
        f"First error: {first}"
    )
