# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.delete_object``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.delete_object"
FUNCTION_NAME = "core_delete_object"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
