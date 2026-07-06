# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.get_object_properties``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.get_object_properties"
FUNCTION_NAME = "core_get_object_properties"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
