# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``cam.add_tool``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cam.add_tool"
FUNCTION_NAME = "cam_add_tool"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
