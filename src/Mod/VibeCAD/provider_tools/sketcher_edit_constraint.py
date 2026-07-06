# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``sketcher.edit_constraint``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "sketcher.edit_constraint"
FUNCTION_NAME = "sketcher_edit_constraint"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
