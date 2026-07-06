# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.list_registered_commands``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.list_registered_commands"
FUNCTION_NAME = "core_list_registered_commands"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
