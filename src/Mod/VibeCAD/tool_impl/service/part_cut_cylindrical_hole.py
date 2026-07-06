# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``part.cut_cylindrical_hole``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': 'Cut a cylindrical hole into a Part object with a one-shot boolean. '
                'For PartDesign Bodies prefer partdesign.hole_from_sketch (parametric, '
                'supports counterbore/countersink); use this for quick holes in '
                'non-Body Part shapes.',
 'name': 'part.cut_cylindrical_hole',
 'parameters': {'properties': {'axis': {'description': 'Global axis of the cylinder (default Z).',
                                        'enum': ['X', 'Y', 'Z'],
                                        'type': 'string'},
                               'depth': {'description': 'Hole depth in mm along the axis (default 20).',
                                         'type': 'number'},
                               'label': {'type': 'string'},
                               'radius': {'description': 'Hole radius in mm (default 2).',
                                          'type': 'number'},
                               'target_name': {'description': 'Object (name or label) to cut the hole into.',
                                               'type': 'string'},
                               'x': {'description': 'Cylinder base X in mm (global).',
                                     'type': 'number'},
                               'y': {'description': 'Cylinder base Y in mm (global).',
                                     'type': 'number'},
                               'z': {'description': 'Cylinder base Z in mm (global).',
                                     'type': 'number'}},
                'required': ['target_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartWorkbench'}


def run(
    service,
    target_name: str,
    label: str = "VibeCAD Hole Cut",
    radius: float = 2.0,
    depth: float = 20.0,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    axis: str = "Z",
) -> dict[str, Any]:
    target = service._get_document_object(target_name)
    if target is None:
        return {"ok": False, "error": f"Target object not found: {target_name}"}
    axis_key = str(axis or "Z").upper()
    if axis_key not in {"X", "Y", "Z"}:
        return {"ok": False, "error": "axis must be X, Y, or Z"}
    if float(radius) <= 0 or float(depth) <= 0:
        return {"ok": False, "error": "radius and depth must be positive"}

    def _cut() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        base = service._get_document_object(target_name)
        if base is None:
            raise RuntimeError(f"Target object not found: {target_name}")
        tool = doc.addObject("Part::Cylinder", "VibeCAD_HoleTool")
        tool.Label = f"{label} Tool"
        tool.Radius = float(radius)
        tool.Height = float(depth)
        tool.Placement.Base = App.Vector(float(x), float(y), float(z))
        if axis_key == "X":
            tool.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90)
        elif axis_key == "Y":
            tool.Placement.Rotation = App.Rotation(App.Vector(1, 0, 0), 90)
        cut = doc.addObject("Part::Cut", "VibeCAD_Cut")
        cut.Label = label
        cut.Base = base
        cut.Tool = tool
        doc.recompute()
        return {
            "object": cut.Name,
            "label": cut.Label,
            "type": cut.TypeId,
            "base": base.Name,
            "tool": tool.Name,
            "radius": float(radius),
            "depth": float(depth),
            "placement": [float(x), float(y), float(z)],
            "axis": axis_key,
        }

    transaction = run_freecad_transaction(
        f"Cut cylindrical hole in {target_name}",
        _cut,
    )
    return {"ok": bool(transaction.get("ok")), "transaction": transaction, "part": domain_runtime.part_summary(service)}
