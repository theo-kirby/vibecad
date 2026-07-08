# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider tool for ``cad.inspect_state``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cad.inspect_state"
FUNCTION_NAME = "cad_inspect_state"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
