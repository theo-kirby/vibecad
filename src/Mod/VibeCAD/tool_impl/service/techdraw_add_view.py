# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``techdraw.add_view``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction
from . import domain_runtime


TOOL_SPEC = {'description': 'Add a TechDraw part view of a model object to an existing drawing '
                'page (create one first with techdraw.create_page).',
 'name': 'techdraw.add_view',
 'parameters': {'properties': {'label': {'description': 'View label shown in the '
                                                        'document tree.',
                                         'type': 'string'},
                               'page_name': {'description': 'TechDraw page object name '
                                                            'or label. Defaults to the '
                                                            'first page.',
                                             'type': 'string'},
                               'scale': {'description': 'View scale factor (default '
                                                        '1.0).',
                                         'type': 'number'},
                               'source_name': {'description': 'Model object name or '
                                                              'label to show in the '
                                                              'drawing view.',
                                               'type': 'string'},
                               'x': {'description': 'View X position on the page in '
                                                    'mm (default 100).',
                                     'type': 'number'},
                               'y': {'description': 'View Y position on the page in '
                                                    'mm (default 100).',
                                     'type': 'number'}},
                'required': ['source_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'TechDrawWorkbench'}


def run(
    service,
    source_name: str,
    page_name: str | None = None,
    label: str = "VibeCAD Drawing View",
    x: float = 100.0,
    y: float = 100.0,
    scale: float = 1.0,
) -> dict[str, Any]:
    page = service._get_techdraw_page(page_name)
    if page is None:
        return {
            "ok": False,
            "error": "TechDraw page not found. Create a page first with techdraw.create_page.",
            "page_name": page_name,
            "active_workbench": "TechDrawWorkbench",
        }
    source = service._get_document_object(source_name)
    if source is None:
        return {
            "ok": False,
            "error": f"Source object not found: {source_name}",
            "active_workbench": "TechDrawWorkbench",
        }

    def _add_view() -> dict[str, Any]:
        active_page = service._get_techdraw_page(page.Name)
        active_source = service._get_document_object(source.Name)
        if active_page is None:
            raise RuntimeError(f"TechDraw page not found: {page.Name}")
        if active_source is None:
            raise RuntimeError(f"Source object not found: {source.Name}")
        doc = active_page.Document
        view = doc.addObject("TechDraw::DrawViewPart", "VibeCAD_View")
        view.Label = label
        view.Source = [active_source]
        if hasattr(view, "X"):
            view.X = float(x)
        if hasattr(view, "Y"):
            view.Y = float(y)
        if hasattr(view, "ScaleType"):
            view.ScaleType = "Custom"
        if hasattr(view, "Scale"):
            view.Scale = float(scale)
        active_page.addView(view)
        doc.recompute()
        return {
            "document": doc.Name,
            "page": active_page.Name,
            "view": view.Name,
            "label": view.Label,
            "source": active_source.Name,
            "x": float(x),
            "y": float(y),
            "scale": float(scale),
        }

    transaction = run_freecad_transaction(
        f"Add TechDraw view of {source.Name}",
        _add_view,
    )
    return {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "techdraw": domain_runtime.techdraw_summary(service, page.Name),
        "active_workbench": "TechDrawWorkbench",
    }
