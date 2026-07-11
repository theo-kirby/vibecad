# SPDX-License-Identifier: LGPL-2.1-or-later

"""Read every used cell of one named spreadsheet."""

from __future__ import annotations

from typing import Any

from . import domain_runtime


MAX_CELLS_RETURNED = 500


TOOL_SPEC = {
    "name": "spreadsheet.read_sheet",
    "description": (
        "Read every used cell of one named spreadsheet: raw content, evaluated "
        "value, and alias. Use this before spreadsheet.set_cells to avoid "
        "overwriting existing data, and to discover aliases for parametric "
        "expressions."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "SpreadsheetWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the Spreadsheet::Sheet object to read."
                ),
            },
        },
        "required": ["sheet_name"],
        "additionalProperties": False,
    },
}


def run(service: Any, sheet_name: str) -> dict[str, Any]:
    clean_name = str(sheet_name or "").strip()
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    sheet = doc.getObject(clean_name) if clean_name else None
    if sheet is None:
        return _invalid(f"Spreadsheet not found by exact internal name: {sheet_name}")
    if not domain_runtime.is_spreadsheet(sheet):
        return _invalid(
            f"Object is not a spreadsheet (Spreadsheet::Sheet): {clean_name}"
        )
    try:
        used_cells = list(sheet.getUsedCells())
    except AttributeError:
        return _invalid(
            "This FreeCAD build does not expose Sheet.getUsedCells; cannot "
            "enumerate cells.",
        )
    except Exception as exc:
        return _invalid(f"Could not enumerate spreadsheet cells: {exc}")
    truncated = len(used_cells) > MAX_CELLS_RETURNED
    cells: list[dict[str, Any]] = []
    for address in used_cells[:MAX_CELLS_RETURNED]:
        record: dict[str, Any] = {"cell": str(address)}
        try:
            record["content"] = str(sheet.getContents(address))
        except Exception as exc:
            record["content_error"] = str(exc)
        try:
            record["value"] = domain_runtime.spreadsheet_display_value(
                sheet.get(address)
            )
        except Exception as exc:
            record["evaluation_error"] = str(exc)
        try:
            alias = sheet.getAlias(address)
            if alias:
                record["alias"] = str(alias)
        except Exception:
            pass
        cells.append(record)
    result: dict[str, Any] = {
        "ok": True,
        "document": doc.Name,
        "sheet": sheet.Name,
        "sheet_label": sheet.Label,
        "cell_count": len(used_cells),
        "cells": cells,
    }
    if truncated:
        result["truncated"] = True
        result["note"] = (
            f"Sheet has {len(used_cells)} used cells; only the first "
            f"{MAX_CELLS_RETURNED} are returned."
        )
    return result


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
