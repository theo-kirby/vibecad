# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``partdesign.create_datum_line``."""

from __future__ import annotations

from typing import Any

from . import domain_runtime
from VibeCADTransactions import run_freecad_transaction


TOOL_SPEC = {'contextual': True,
 'description': 'Create a PartDesign Datum Line in a Body, referenced to an origin '
                'axis with optional offset (mm) and rotation (deg). Use offsets to '
                'place revolve or pattern axes away from the origin.',
 'name': 'partdesign.create_datum_line',
 'parameters': {'properties': {'body_name': {'description': 'Optional target Body internal name or visible label.',
                                              'type': 'string'},
                               'label': {'type': 'string'},
                               'map_mode': {'description': 'Native attachment map mode.',
                                            'type': 'string'},
                               'offset_x': {'description': 'Offset along local X in mm (default 0).',
                                            'type': 'number'},
                               'offset_y': {'description': 'Offset along local Y in mm (default 0).',
                                            'type': 'number'},
                               'offset_z': {'description': 'Offset along local Z in mm (default 0).',
                                            'type': 'number'},
                               'rotation_axis': {'description': "Local axis for rotation_deg: 'x', 'y', or 'z' (default 'z').",
                                                 'enum': ['x', 'y', 'z'],
                                                 'type': 'string'},
                               'rotation_deg': {'description': 'Rotation about rotation_axis in degrees (default 0).',
                                                'type': 'number'},
                               'support_axis': {'enum': ['X_Axis', 'Y_Axis', 'Z_Axis'],
                                                'type': 'string'}},
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartDesignWorkbench'}


_AXIS_VECTORS = {'x': (1.0, 0.0, 0.0), 'y': (0.0, 1.0, 0.0), 'z': (0.0, 0.0, 1.0)}


def run(
    service,
    label: str = "VibeCAD Datum Line",
    support_axis: str = "Z_Axis",
    map_mode: str = "TwoPointLine",
    body_name: str | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    rotation_axis: str = "z",
    rotation_deg: float = 0.0,
) -> dict[str, Any]:
    requested_support = str(support_axis or "Z_Axis")
    if requested_support not in {"X_Axis", "Y_Axis", "Z_Axis"}:
        return {"ok": False, "error": "support_axis must be X_Axis, Y_Axis, or Z_Axis."}
    axis_key = str(rotation_axis or "z").lower()
    if axis_key not in _AXIS_VECTORS:
        return {"ok": False, "error": "rotation_axis must be 'x', 'y', or 'z'."}
    try:
        offsets = (float(offset_x), float(offset_y), float(offset_z))
        angle = float(rotation_deg)
    except (TypeError, ValueError):
        return {"ok": False, "error": "offset_x/offset_y/offset_z (mm) and rotation_deg must be numbers."}

    def _create() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        body = service._get_partdesign_body(body_name) if body_name else service._get_partdesign_body()
        if body is None:
            raise RuntimeError("No PartDesign Body found for datum line.")
        support = service._partdesign_origin_feature(body, requested_support)
        if support is None:
            raise RuntimeError(f"Body origin axis not found: {requested_support}")
        datum = doc.addObject("PartDesign::Line", "VibeCAD_DatumLine")
        datum.Label = label or "VibeCAD Datum Line"
        datum.AttachmentSupport = [(support, "")]
        datum.MapMode = str(map_mode or "TwoPointLine")
        if any(abs(value) > 1e-12 for value in offsets) or abs(angle) > 1e-12:
            axis_vec = App.Vector(*_AXIS_VECTORS[axis_key])
            datum.AttachmentOffset = App.Placement(
                App.Vector(*offsets), App.Rotation(axis_vec, angle)
            )
        body.addObject(datum)
        doc.recompute()
        return {
            "document": doc.Name,
            "body": body.Name,
            "datum": datum.Name,
            "label": getattr(datum, "Label", datum.Name),
            "type": getattr(datum, "TypeId", ""),
            "support_axis": requested_support,
            "map_mode": getattr(datum, "MapMode", None),
            "offset": {"x": offsets[0], "y": offsets[1], "z": offsets[2]},
            "rotation": {"axis": axis_key, "deg": angle},
            "placement": {
                "base": [
                    datum.Placement.Base.x,
                    datum.Placement.Base.y,
                    datum.Placement.Base.z,
                ],
            },
            "shape": domain_runtime.shape_summary(datum),
        }

    transaction = run_freecad_transaction(
        f"Create PartDesign datum line on {requested_support}",
        _create,
    )
    result = transaction.get("result", {}) if isinstance(transaction.get("result"), dict) else {}
    return {
        "ok": bool(transaction.get("ok")),
        **({"error": transaction.get("error"), "recoverable": True} if not transaction.get("ok") else {}),
        "transaction": transaction,
        "datum": result.get("datum"),
        "partdesign": domain_runtime.partdesign_summary(service),
    }
