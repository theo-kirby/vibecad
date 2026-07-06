# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``core.wait_for_user_gui_action``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "core.wait_for_user_gui_action"
FUNCTION_NAME = "core_wait_for_user_gui_action"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
