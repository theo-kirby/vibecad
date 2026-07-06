# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``part.cut_cylindrical_hole``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "part.cut_cylindrical_hole"
FUNCTION_NAME = "part_cut_cylindrical_hole"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
