# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``cam.define_machine``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cam.define_machine"
FUNCTION_NAME = "cam_define_machine"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
