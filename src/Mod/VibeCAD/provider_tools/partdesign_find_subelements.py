# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.find_subelements``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.find_subelements"
FUNCTION_NAME = "partdesign_find_subelements"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
