# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.capture_view_screenshot``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.capture_view_screenshot"
FUNCTION_NAME = "core_capture_view_screenshot"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
