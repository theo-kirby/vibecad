# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``spreadsheet.get_sheet``."""

from __future__ import annotations

TOOL_SPEC = {'description': 'Return non-empty cells from a Spreadsheet sheet within a bounded scan '
                'range.',
 'name': 'spreadsheet.get_sheet',
 'parameters': {'properties': {'max_columns': {'description': 'Columns to scan, 1-26 '
                                                              '(default 8).',
                                               'type': 'integer'},
                               'max_rows': {'description': 'Rows to scan, 1-200 '
                                                           '(default 20).',
                                            'type': 'integer'},
                               'sheet_name': {'description': 'Spreadsheet object name '
                                                             'or label. Defaults to '
                                                             'the first sheet.',
                                              'type': 'string'}},
                'type': 'object'},
 'safety': 'READ',
 'workbench': 'SpreadsheetWorkbench'}


def run(service, **kwargs):
    sheet_name = kwargs.get("sheet_name")
    max_columns = kwargs.get("max_columns", 8)
    max_rows = kwargs.get("max_rows", 20)
    sheet = service._get_spreadsheet(sheet_name)
    sheets = service._spreadsheet_objects()
    if sheet is None:
        return {
            "found": False,
            "requested": sheet_name,
            "sheet_count": len(sheets),
            "sheets": [service._object_summary(item) for item in sheets],
        }

    safe_columns = max(1, min(int(max_columns), 26))
    safe_rows = max(1, min(int(max_rows), 200))
    cells = []
    for column_index in range(1, safe_columns + 1):
        for row in range(1, safe_rows + 1):
            cell = service._cell_name(column_index, row)
            try:
                contents = sheet.getContents(cell)
            except Exception:
                contents = ""
            if contents in ("", None):
                continue
            try:
                value = sheet.get(cell)
            except Exception as exc:
                value = f"<error: {exc}>"
            cells.append(
                {
                    "cell": cell,
                    "contents": service._short_value(contents),
                    "value": service._short_value(value),
                }
            )
    return {
        "found": True,
        "sheet": service._object_summary(sheet),
        "scanned_columns": safe_columns,
        "scanned_rows": safe_rows,
        "non_empty_count": len(cells),
        "cells": cells,
    }
