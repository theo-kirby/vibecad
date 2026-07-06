# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.add_hole_pattern``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.add_hole_pattern"
FUNCTION_NAME = "sketcher_add_hole_pattern"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
