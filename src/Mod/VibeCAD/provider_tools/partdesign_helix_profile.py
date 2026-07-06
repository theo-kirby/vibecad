# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.helix_profile``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.helix_profile"
FUNCTION_NAME = "partdesign_helix_profile"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
