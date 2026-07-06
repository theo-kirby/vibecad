# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``partdesign.get_bodies``."""

from __future__ import annotations

TOOL_SPEC = {'description': 'Return PartDesign bodies, contained features, and tip feature from '
                'the active document.',
 'name': 'partdesign.get_bodies',
 'parameters': {'properties': {'body_name': {'description': 'Body object name or '
                                                            'label. Defaults to the '
                                                            'first body.',
                                             'type': 'string'}},
                'type': 'object'},
 'safety': 'READ',
 'workbench': 'PartDesignWorkbench'}


def run(service, body_name: str | None = None, **_kwargs):
    bodies = service._partdesign_bodies()
    body = service._get_partdesign_body(body_name)
    return {
        "body_count": len(bodies),
        "bodies": [service._partdesign_body_summary(item) for item in bodies],
        "selected_body": service._partdesign_body_summary(body) if body else None,
    }
