# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.create_datum_line``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.create_datum_line"
FUNCTION_NAME = "partdesign_create_datum_line"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
