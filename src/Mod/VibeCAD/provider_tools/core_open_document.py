# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.open_document``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.open_document"
FUNCTION_NAME = "core_open_document"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
