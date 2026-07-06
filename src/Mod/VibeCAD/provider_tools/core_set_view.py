# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.set_view``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.set_view"
FUNCTION_NAME = "core_set_view"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
