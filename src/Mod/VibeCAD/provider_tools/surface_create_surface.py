# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``surface.create_surface``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "surface.create_surface"
FUNCTION_NAME = "surface_create_surface"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
