# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``assembly.check_interference``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "assembly.check_interference"
FUNCTION_NAME = "assembly_check_interference"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
