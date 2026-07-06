# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``part.set_placement``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'description': "Set an object's global placement: position plus yaw/pitch/roll "
                'rotation. For components inside a native Assembly use '
                'assembly.set_component_placement instead.',
 'name': 'part.set_placement',
 'parameters': {'properties': {'object_name': {'description': 'Object name or label to reposition.',
                                               'type': 'string'},
                               'pitch_degrees': {'description': 'Rotation about Y axis in degrees.',
                                                 'type': 'number'},
                               'roll_degrees': {'description': 'Rotation about X axis in degrees.',
                                                'type': 'number'},
                               'x': {'description': 'Global X position in mm.',
                                     'type': 'number'},
                               'y': {'description': 'Global Y position in mm.',
                                     'type': 'number'},
                               'yaw_degrees': {'description': 'Rotation about Z axis in degrees.',
                                               'type': 'number'},
                               'z': {'description': 'Global Z position in mm.',
                                     'type': 'number'}},
                'required': ['object_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartWorkbench'}


def run(
    service,
    object_name: str,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    yaw_degrees: float = 0.0,
    pitch_degrees: float = 0.0,
    roll_degrees: float = 0.0,
) -> dict[str, Any]:
    obj = service._get_document_object(object_name)
    if obj is None:
        return {"ok": False, "error": f"Object not found: {object_name}"}

    def _set() -> dict[str, Any]:
        import FreeCAD as App

        target = service._get_document_object(object_name)
        if target is None:
            raise RuntimeError(f"Object not found: {object_name}")
        rotation = (
            App.Rotation(App.Vector(0, 0, 1), float(yaw_degrees))
            * App.Rotation(App.Vector(0, 1, 0), float(pitch_degrees))
            * App.Rotation(App.Vector(1, 0, 0), float(roll_degrees))
        )
        target.Placement = App.Placement(
            App.Vector(float(x), float(y), float(z)),
            rotation,
        )
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        return {
            "object": target.Name,
            "label": getattr(target, "Label", target.Name),
            "placement": [float(x), float(y), float(z)],
            "rotation_degrees": [
                float(yaw_degrees),
                float(pitch_degrees),
                float(roll_degrees),
            ],
        }

    transaction = run_freecad_transaction(
        f"Set placement: {object_name}",
        _set,
    )
    return {"ok": bool(transaction.get("ok")), "transaction": transaction}
