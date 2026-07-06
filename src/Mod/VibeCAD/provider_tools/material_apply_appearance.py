# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``material.apply_appearance``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "material.apply_appearance"
FUNCTION_NAME = "material_apply_appearance"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
