# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider tool for ``cad.define_envelope``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cad.define_envelope"
FUNCTION_NAME = "cad_define_envelope"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
