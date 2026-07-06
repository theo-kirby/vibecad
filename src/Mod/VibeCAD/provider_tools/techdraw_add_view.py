# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``techdraw.add_view``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "techdraw.add_view"
FUNCTION_NAME = "techdraw_add_view"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
