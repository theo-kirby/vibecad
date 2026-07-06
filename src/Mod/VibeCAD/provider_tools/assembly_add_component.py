# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``assembly.add_component``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "assembly.add_component"
FUNCTION_NAME = "assembly_add_component"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
