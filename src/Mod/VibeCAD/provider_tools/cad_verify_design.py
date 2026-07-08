# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider tool for ``cad.verify_design``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cad.verify_design"
FUNCTION_NAME = "cad_verify_design"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
