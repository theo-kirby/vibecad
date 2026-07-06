# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.create_body``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.create_body"
FUNCTION_NAME = "partdesign_create_body"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
