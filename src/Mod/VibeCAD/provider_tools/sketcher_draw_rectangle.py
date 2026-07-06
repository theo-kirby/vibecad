# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.draw_rectangle``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.draw_rectangle"
FUNCTION_NAME = "sketcher_draw_rectangle"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
