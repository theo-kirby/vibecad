# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.pattern``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.pattern"
FUNCTION_NAME = "partdesign_pattern"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
