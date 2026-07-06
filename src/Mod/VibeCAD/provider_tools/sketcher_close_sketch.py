# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.close_sketch``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.close_sketch"
FUNCTION_NAME = "sketcher_close_sketch"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
