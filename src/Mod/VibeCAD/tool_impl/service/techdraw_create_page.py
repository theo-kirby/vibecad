# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native TechDraw drawing page with a standard template."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_TEMPLATE_FILES = {
    "a4_landscape": "ISO/A4_Landscape_blank.svg",
    "a3_landscape": "ISO/A3_Landscape_blank.svg",
    "a2_landscape": "ISO/A2_Landscape_blank.svg",
    "a1_landscape": "ISO/A1_Landscape_blank.svg",
    "a0_landscape": "ISO/A0_Landscape_blank.svg",
    "a4_portrait": "ISO/A4_Portrait_blank.svg",
}


TOOL_SPEC = {
    "name": "techdraw.create_page",
    "description": (
        "Create one native TechDraw drawing page with a blank ISO sheet "
        "template. The page starts empty; add projected views of 3D objects "
        "with techdraw.add_view, then dimensions and notes."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "TechDrawWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "sheet_size": {
                "type": "string",
                "enum": sorted(_TEMPLATE_FILES),
                "description": (
                    "Standard sheet size and orientation for the page "
                    "template: a0_landscape through a4_landscape, or "
                    "a4_portrait."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new page, e.g. 'BracketDrawing'.",
            },
        },
        "required": ["sheet_size", "label"],
        "additionalProperties": False,
    },
}


def run(service: Any, sheet_size: str, label: str) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    template_relative = _TEMPLATE_FILES.get(str(sheet_size or ""))
    if template_relative is None:
        return _invalid(
            "sheet_size must be one of: " + ", ".join(sorted(_TEMPLATE_FILES))
        )
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")

    def create() -> dict[str, Any]:
        import os

        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        templates_dir = os.path.join(
            App.getResourceDir(), "Mod", "TechDraw", "Templates"
        )
        template_path = os.path.join(templates_dir, *template_relative.split("/"))
        if not os.path.isfile(template_path):
            fallback = os.path.join(templates_dir, "Default_Template_A4_Landscape.svg")
            if not os.path.isfile(fallback):
                raise RuntimeError(
                    "No TechDraw template files found in this FreeCAD "
                    f"installation (looked in {templates_dir})."
                )
            template_path = fallback
        page = active.addObject("TechDraw::DrawPage", "Page")
        template = active.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = template_path
        page.Template = template
        page.Label = clean_label
        active.recompute()
        return {
            "document": active.Name,
            "page": page.Name,
            "page_label": page.Label,
            "template_file": os.path.basename(template_path),
        }

    transaction = run_freecad_transaction(
        f"Create TechDraw page: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "create_page"},
        next_action=("Add projected views of exact 3D objects with techdraw.add_view."),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
