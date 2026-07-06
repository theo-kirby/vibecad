# SPDX-License-Identifier: LGPL-2.1-or-later

"""Provider function tool for ``model.build_from_script``.

Only surfaced when the user enables script mode in preferences; in that
mode this is the sole geometry write path.
"""

from __future__ import annotations

from .base import create_provider_tool


TOOL_NAME = "model.build_from_script"
FUNCTION_NAME = "model_build_from_script"


def create(schema, conn, FunctionTool):
    return create_provider_tool(TOOL_NAME, FUNCTION_NAME, schema, conn, FunctionTool)
