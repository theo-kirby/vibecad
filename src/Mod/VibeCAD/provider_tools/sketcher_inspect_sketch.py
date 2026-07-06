# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.inspect_sketch``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.inspect_sketch"
FUNCTION_NAME = "sketcher_inspect_sketch"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
