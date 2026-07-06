# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.revolve``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.revolve"
FUNCTION_NAME = "partdesign_revolve"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
