# SPDX-License-Identifier: LGPL-2.1-or-later

"""Write a batch of cells (content and aliases) to one named spreadsheet."""

from __future__ import annotations

import re
from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_CELL_PATTERN = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,4}$")
_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAX_CELLS_PER_CALL = 100


TOOL_SPEC = {
    "name": "spreadsheet.set_cells",
    "description": (
        "Write a batch of cells to one named spreadsheet in a single "
        "transaction: numbers, text, formulas (content starting with '='), and "
        "optional aliases. Aliased cells can be referenced from parametric "
        "expressions in other objects as SheetName.alias. Existing cell content "
        "is overwritten; read the sheet first with spreadsheet.read_sheet when "
        "unsure."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "SpreadsheetWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the Spreadsheet::Sheet object to write."
                ),
            },
            "cells": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CELLS_PER_CALL,
                "description": (
                    "Batch of cell writes applied in order within one "
                    "transaction. Each cell address may appear at most once."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "cell": {
                            "type": "string",
                            "pattern": "^[A-Za-z]{1,3}[1-9][0-9]{0,4}$",
                            "description": (
                                "Exact cell address, for example 'A1' or 'B12'."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Cell content as a string: a number ('42'), "
                                "text, or a formula starting with '=' (for "
                                "example '=A1*2')."
                            ),
                        },
                        "alias": {
                            "type": "string",
                            "description": (
                                "Optional alias for this cell so expressions "
                                "elsewhere can reference it as SheetName.alias. "
                                "Must start with a letter or underscore and use "
                                "only letters, digits, and underscores."
                            ),
                        },
                    },
                    "required": ["cell", "content"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["sheet_name", "cells"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    sheet_name: str,
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    clean_name = str(sheet_name or "").strip()
    doc = service._active_document()
    sheet = doc.getObject(clean_name) if doc is not None and clean_name else None
    if sheet is None:
        return _invalid(f"Spreadsheet not found by exact internal name: {sheet_name}")
    if not domain_runtime.is_spreadsheet(sheet):
        return _invalid(
            f"Object is not a spreadsheet (Spreadsheet::Sheet): {clean_name}"
        )
    if not isinstance(cells, list) or not cells:
        return _invalid("cells must contain at least one cell write.")
    if len(cells) > MAX_CELLS_PER_CALL:
        return _invalid(
            f"cells accepts at most {MAX_CELLS_PER_CALL} entries per call; "
            "split the batch."
        )
    writes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(cells):
        if not isinstance(entry, dict):
            return _invalid(f"cells[{index}] must be an object.")
        address = str(entry.get("cell") or "").strip().upper()
        if not _CELL_PATTERN.fullmatch(address):
            return _invalid(
                f"cells[{index}].cell is not a valid cell address: "
                f"{entry.get('cell')!r}"
            )
        if address in seen:
            return _invalid(
                f"cells[{index}] repeats cell {address}; each cell may appear "
                "once per call."
            )
        seen.add(address)
        content = entry.get("content")
        if not isinstance(content, str):
            return _invalid(
                f"cells[{index}].content must be a string (use '42' for numbers)."
            )
        alias_value = entry.get("alias")
        alias: str | None = None
        if alias_value is not None:
            alias = str(alias_value).strip()
            if not _ALIAS_PATTERN.fullmatch(alias):
                return _invalid(
                    f"cells[{index}].alias must start with a letter or "
                    "underscore and use only letters, digits, and underscores: "
                    f"{alias!r}"
                )
            if _CELL_PATTERN.fullmatch(alias.upper()):
                return _invalid(
                    f"cells[{index}].alias must not look like a cell address: {alias!r}"
                )
        writes.append({"cell": address, "content": content, "alias": alias})

    def apply() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(clean_name)
        if target is None:
            raise RuntimeError("The spreadsheet no longer exists.")
        # Aliases first so formulas in the same batch can reference them.
        for write in writes:
            if write["alias"]:
                target.setAlias(write["cell"], write["alias"])
        for write in writes:
            target.set(write["cell"], write["content"])
        active.recompute()
        written: list[dict[str, Any]] = []
        for write in writes:
            record: dict[str, Any] = {
                "cell": write["cell"],
                "content": write["content"],
            }
            if write["alias"]:
                record["alias"] = write["alias"]
            try:
                record["value"] = domain_runtime.spreadsheet_display_value(
                    target.get(write["cell"])
                )
            except Exception as exc:
                record["evaluation_error"] = str(exc)
            written.append(record)
        return {
            "document": active.Name,
            "sheet": target.Name,
            "sheet_label": target.Label,
            "cell_count": len(written),
            "cells": written,
        }

    transaction = run_freecad_transaction(
        f"Set spreadsheet cells: {clean_name}",
        apply,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "set_cells"},
        next_action=(
            "Check the returned evaluated values; any evaluation_error means "
            "the formula or reference in that cell needs correcting."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
