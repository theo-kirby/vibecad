# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``techdraw.create_page``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "techdraw.create_page"
FUNCTION_NAME = "techdraw_create_page"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
