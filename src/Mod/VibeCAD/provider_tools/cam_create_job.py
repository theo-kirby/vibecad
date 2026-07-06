# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``cam.create_job``."""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "cam.create_job"
FUNCTION_NAME = "cam_create_job"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
