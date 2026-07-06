# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.get_view_state``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.get_view_state"
FUNCTION_NAME = "core_get_view_state"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
