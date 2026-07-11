# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native Surface sections loft through exact profile curves."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime
from .surface_fill import build_link_sub_list, validate_curve_refs


TOOL_SPEC = {
    "name": "surface.loft",
    "description": (
        "Create one native Surface sections loft that blends smoothly through "
        "two or more exact profile curves in order. Profiles must not "
        "intersect each other; list them in the order the surface should pass "
        "through them. Resolve edge names with part.find_subelements first."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "SurfaceWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "profiles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": (
                                "Exact internal name of the profile curve object."
                            ),
                        },
                        "edge_name": {
                            "type": "string",
                            "description": (
                                "Exact edge name such as Edge1 on that object; "
                                "empty string to use the whole object as the "
                                "profile (for single-wire curves)."
                            ),
                        },
                    },
                    "required": ["object_name", "edge_name"],
                    "additionalProperties": False,
                },
                "minItems": 2,
                "description": (
                    "Profile curve references, in the order the surface "
                    "passes through them."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new loft surface.",
            },
        },
        "required": ["profiles", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    profiles: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    refs, error = validate_curve_refs(service, profiles, "profiles")
    if error is not None:
        return _invalid(error)
    if len(refs) < 2:
        return _invalid("profiles must contain at least two curve references.")

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        sections = active.addObject("Surface::Sections", "SurfaceLoft")
        sections.Label = clean_label
        sections.NSections = build_link_sub_list(active, refs)
        active.recompute()
        return {
            "document": active.Name,
            "feature": sections.Name,
            "feature_label": sections.Label,
            "feature_type": sections.TypeId,
            "profiles": [
                {"object_name": name, "edge_name": edge} for name, edge in refs
            ],
            "shape": domain_runtime.shape_summary(sections),
            "feature_state": domain_runtime.feature_state_summary(sections),
        }

    transaction = run_freecad_transaction(
        f"Create surface loft: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(transaction, operation="surface_loft")


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
