# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.get_tool_shape_report``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.get_tool_shape_report"
FUNCTION_NAME = "core_get_tool_shape_report"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
