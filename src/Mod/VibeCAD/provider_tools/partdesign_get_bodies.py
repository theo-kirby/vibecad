# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.get_bodies``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.get_bodies"
FUNCTION_NAME = "partdesign_get_bodies"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
