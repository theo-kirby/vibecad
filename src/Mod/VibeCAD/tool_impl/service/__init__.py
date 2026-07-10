# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service-backed VibeCAD tool registration.

Each module in this package owns one provider-visible tool shape and must expose
``run(service, **kwargs)``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

TOOL_MODULE_NAMES = (
    "conversation_ask_user",
    "project_update_design_document",
    "core_capture_view_screenshot",
    "core_set_view",
    "core_delete_object",
    "partdesign_create_body",
    "partdesign_create_sketch",
    "partdesign_create_datum_plane",
    "partdesign_create_datum_axis",
    "partdesign_create_datum_point",
    "partdesign_create_shape_binder",
    "partdesign_create_subshape_binder",
    "partdesign_additive_primitive",
    "partdesign_subtractive_primitive",
    "partdesign_pad",
    "partdesign_pocket",
    "partdesign_hole",
    "partdesign_revolution",
    "partdesign_groove",
    "partdesign_additive_loft",
    "partdesign_subtractive_loft",
    "partdesign_additive_pipe",
    "partdesign_subtractive_pipe",
    "partdesign_additive_helix",
    "partdesign_subtractive_helix",
    "partdesign_linear_pattern",
    "partdesign_polar_pattern",
    "partdesign_mirror",
    "partdesign_multi_transform",
    "partdesign_fillet",
    "partdesign_chamfer",
    "partdesign_draft",
    "partdesign_thickness",
    "partdesign_boolean",
    "partdesign_edit_feature",
    "partdesign_set_tip",
    "partdesign_find_subelements",
    "partdesign_measure",
)


def register_tools(registry: Any, service: Any) -> None:
    for module_name in TOOL_MODULE_NAMES:
        module = import_module(f"{__name__}.{module_name}")
        spec = module.TOOL_SPEC
        module_run = getattr(module, "run", None)
        if not callable(module_run):
            raise ValueError(f"VibeCAD service tool module has no run(): {module_name}")

        def handler(_module=module, **kwargs):
            return _module.run(service, **kwargs)

        registry.register_spec(spec, handler)
