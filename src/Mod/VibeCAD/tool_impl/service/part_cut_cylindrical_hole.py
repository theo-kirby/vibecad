# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``part.cut_cylindrical_hole``."""

from __future__ import annotations

from numbers import Real
from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': 'Cut a cylindrical hole into a Part object with a one-shot boolean. '
                'For PartDesign Bodies prefer partdesign.hole_from_sketch (parametric, '
                'supports counterbore/countersink); use this for quick holes in '
                'non-Body Part shapes.',
 'name': 'part.cut_cylindrical_hole',
 'parameters': {'properties': {'axis': {'description': 'Global axis of the cylinder.',
                                        'enum': ['X', 'Y', 'Z'],
                                        'type': 'string'},
                               'depth': {'description': 'Hole depth in mm along the axis.',
                                         'type': 'number'},
                               'label': {'type': 'string'},
                               'radius': {'description': 'Hole radius in mm.',
                                          'type': 'number'},
                               'target_name': {'description': 'Object (name or label) to cut the hole into.',
                                               'type': 'string'},
                               'x': {'description': 'Cylinder base X in mm (global).',
                                     'type': 'number'},
                               'y': {'description': 'Cylinder base Y in mm (global).',
                                     'type': 'number'},
                               'z': {'description': 'Cylinder base Z in mm (global).',
                                     'type': 'number'}},
                'required': ['target_name', 'radius', 'depth', 'x', 'y', 'z', 'axis'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartWorkbench'}


def _number_arg(name: str, value: Any, *, positive: bool = False) -> tuple[bool, float | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit number."
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{name} must be a number."
    number = float(value)
    if positive and number <= 0:
        return False, f"{name} must be positive."
    return True, number


def run(
    service,
    target_name: str,
    label: str = "VibeCAD Hole Cut",
    radius: float | None = None,
    depth: float | None = None,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    axis: str | None = None,
) -> dict[str, Any]:
    target = service._get_document_object(target_name)
    if target is None:
        return {"ok": False, "error": f"Target object not found: {target_name}"}
    parsed: dict[str, float] = {}
    for name, value, positive in (
        ("radius", radius, True),
        ("depth", depth, True),
        ("x", x, False),
        ("y", y, False),
        ("z", z, False),
    ):
        ok, result = _number_arg(name, value, positive=positive)
        if not ok:
            return {"ok": False, "error": str(result), "retry_same_call": False}
        parsed[name] = float(result)
    if axis is None or not str(axis).strip():
        return {"ok": False, "error": "axis is required and must be X, Y, or Z.", "retry_same_call": False}
    axis_key = str(axis).strip().upper()
    if axis_key not in {"X", "Y", "Z"}:
        return {"ok": False, "error": "axis must be X, Y, or Z.", "retry_same_call": False}

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
        tool.Radius = parsed["radius"]
        tool.Height = parsed["depth"]
        tool.Placement.Base = App.Vector(parsed["x"], parsed["y"], parsed["z"])
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
            "radius": parsed["radius"],
            "depth": parsed["depth"],
            "placement": [parsed["x"], parsed["y"], parsed["z"]],
            "axis": axis_key,
        }

    transaction = run_freecad_transaction(
        f"Cut cylindrical hole in {target_name}",
        _cut,
    )
    return {"ok": bool(transaction.get("ok")), "transaction": transaction, "part": domain_runtime.part_summary(service)}
