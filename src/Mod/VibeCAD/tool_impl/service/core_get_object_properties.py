# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_object_properties``."""

from __future__ import annotations


TOOL_SPEC = {'contextual': True,
 'description': 'Return all readable properties of one active-document object; use '
                'core.list_workbench_objects to survey many objects at once.',
 'name': 'core.get_object_properties',
 'parameters': {'properties': {'object_name': {'description': 'Internal name or label of '
                                                              'the object to inspect.',
                                               'type': 'string'}},
                'required': ['object_name'],
                'type': 'object'},
 'safety': 'READ'}


def run(service, **kwargs):
    object_name = kwargs["object_name"]
    obj = service._get_document_object(object_name)
    if obj is None:
        return {"found": False, "object_name": object_name}
    properties = {}
    for prop in list(getattr(obj, "PropertiesList", []) or []):
        try:
            properties[prop] = service._short_value(getattr(obj, prop))
        except Exception as exc:
            properties[prop] = f"<error: {exc}>"
    return {
        "found": True,
        "object": service._document_object_summary(obj),
        "properties": properties,
    }
