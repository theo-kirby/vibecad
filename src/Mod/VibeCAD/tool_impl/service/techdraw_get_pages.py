# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``techdraw.get_pages``."""

from __future__ import annotations

TOOL_SPEC = {'description': 'Return TechDraw drawing pages, templates, and views from the active '
                'document.',
 'name': 'techdraw.get_pages',
 'parameters': {'properties': {'page_name': {'description': 'TechDraw page object name '
                                                            'or label. Defaults to the '
                                                            'first page.',
                                             'type': 'string'}},
                'type': 'object'},
 'safety': 'READ',
 'workbench': 'TechDrawWorkbench'}


def run(service, **kwargs):
    page_name = kwargs.get("page_name")
    pages = service._techdraw_pages()
    page = service._get_techdraw_page(page_name)
    return {
        "page_count": len(pages),
        "pages": [service._techdraw_page_summary(item) for item in pages],
        "selected_page": service._techdraw_page_summary(page) if page else None,
    }
