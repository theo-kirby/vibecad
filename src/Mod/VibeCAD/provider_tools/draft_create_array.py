# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``draft.create_array``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "draft.create_array"
FUNCTION_NAME = "draft_create_array"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
