# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``partdesign.set_feature_dimensions``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "partdesign.set_feature_dimensions"
FUNCTION_NAME = "partdesign_set_feature_dimensions"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
