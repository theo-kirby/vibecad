# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``techdraw.create_page``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction
from . import domain_runtime


TOOL_SPEC = {'description': 'Create a TechDraw drawing page for 2D drawings of 3D models; then '
                'place model views on it with techdraw.add_view.',
 'name': 'techdraw.create_page',
 'parameters': {'properties': {'label': {'description': 'Page label shown in the '
                                                        'document tree.',
                                         'type': 'string'},
                               'with_template': {'description': 'Attach an empty SVG '
                                                                'template (default '
                                                                'false).',
                                                 'type': 'boolean'}},
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'TechDrawWorkbench'}


def run(
    service,
    label: str = "VibeCAD Drawing Page",
    with_template: bool = False,
) -> dict[str, Any]:
    def _create_page() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument or App.newDocument()
        page = doc.addObject("TechDraw::DrawPage", "VibeCAD_Page")
        page.Label = label
        template_name = None
        if bool(with_template):
            template = doc.addObject("TechDraw::DrawSVGTemplate", "VibeCAD_Template")
            template.Label = f"{label} Template"
            page.Template = template
            template_name = template.Name
        doc.recompute()
        return {
            "document": doc.Name,
            "page": page.Name,
            "label": page.Label,
            "type": page.TypeId,
            "template": template_name,
        }

    transaction = run_freecad_transaction(
        f"Create TechDraw page: {label}",
        _create_page,
    )
    return {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "techdraw": domain_runtime.techdraw_summary(service, label),
        "active_workbench": "TechDrawWorkbench",
    }
