# SPDX-License-Identifier: LGPL-2.1-or-later

"""Focused native PartDesign additive primitive tool."""

from __future__ import annotations

from typing import Any

from . import partdesign_primitive_feature


TOOL_SPEC = {
    "name": "partdesign.additive_primitive",
    "description": (
        "Create one native editable additive Box, Cylinder, Sphere, Cone, Ellipsoid, Torus, "
        "Prism, or Wedge in an exact Body from a geometry-specific definition and placement."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": partdesign_primitive_feature.PARAMETERS,
}


def run(service: Any, **arguments: Any) -> dict[str, Any]:
    return partdesign_primitive_feature.run(
        service,
        operation="additive_primitive",
        **arguments,
    )
