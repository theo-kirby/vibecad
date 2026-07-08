# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider tool for ``cad.create_profile``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cad.create_profile"
FUNCTION_NAME = "cad_create_profile"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
