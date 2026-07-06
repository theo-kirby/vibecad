# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``assembly.set_component_placement``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "assembly.set_component_placement"
FUNCTION_NAME = "assembly_set_component_placement"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
