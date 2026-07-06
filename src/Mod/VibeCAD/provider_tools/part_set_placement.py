# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``part.set_placement``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "part.set_placement"
FUNCTION_NAME = "part_set_placement"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
