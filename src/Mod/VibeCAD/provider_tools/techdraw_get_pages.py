# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``techdraw.get_pages``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "techdraw.get_pages"
FUNCTION_NAME = "techdraw_get_pages"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
