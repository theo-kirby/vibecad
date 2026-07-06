# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.report_tool_shape_gap``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.report_tool_shape_gap"
FUNCTION_NAME = "core_report_tool_shape_gap"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
