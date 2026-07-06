# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.set_geometry_name``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.set_geometry_name"
FUNCTION_NAME = "sketcher_set_geometry_name"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
