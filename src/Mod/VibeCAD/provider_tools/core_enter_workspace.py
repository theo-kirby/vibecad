# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.enter_workspace``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.enter_workspace"
FUNCTION_NAME = "core_enter_workspace"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
