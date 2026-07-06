# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.list_workbenches``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.list_workbenches"
FUNCTION_NAME = "core_list_workbenches"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
