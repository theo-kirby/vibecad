# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.delete_items``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.delete_items"
FUNCTION_NAME = "sketcher_delete_items"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
