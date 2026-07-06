# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.move_point``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.move_point"
FUNCTION_NAME = "sketcher_move_point"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
