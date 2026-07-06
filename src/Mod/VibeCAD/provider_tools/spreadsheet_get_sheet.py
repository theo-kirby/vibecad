# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``spreadsheet.get_sheet``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "spreadsheet.get_sheet"
FUNCTION_NAME = "spreadsheet_get_sheet"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
