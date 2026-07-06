# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``material.apply_appearance``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': "Apply diffuse color and transparency to an object's native "
                'ShapeMaterial appearance.',
 'name': 'material.apply_appearance',
 'parameters': {'properties': {'diffuse_color': {'description': 'RGB triple, each component 0.0-1.0, e.g. [0.8, 0.1, 0.1].',
                                                 'items': {'type': 'number'},
                                                 'maxItems': 3,
                                                 'minItems': 3,
                                                 'type': 'array'},
                               'object_name': {'description': 'Object name or label to color.',
                                               'type': 'string'},
                               'transparency': {'description': 'Transparency 0.0 (opaque, default) to 1.0 (invisible).',
                                                'type': 'number'}},
                'required': ['object_name', 'diffuse_color'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'MaterialWorkbench'}


def run(
    service,
    object_name: str,
    diffuse_color: list[float] | tuple[float, float, float],
    transparency: float = 0.0,
) -> dict[str, Any]:
    try:
        rgb = service._coerce_rgb(diffuse_color)
        alpha = max(0.0, min(float(transparency), 1.0))
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "active_workbench": "MaterialWorkbench"}
    obj = service._get_document_object(object_name)
    if obj is None:
        return {"ok": False, "error": f"Object not found: {object_name}", "active_workbench": "MaterialWorkbench"}
    if not hasattr(obj, "ShapeMaterial"):
        return {
            "ok": False,
            "error": f"Object does not expose ShapeMaterial: {object_name}",
            "active_workbench": "MaterialWorkbench",
            "object": service._object_summary(obj),
        }

    def _apply() -> dict[str, Any]:
        import FreeCAD as App
        import Materials

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target = service._get_document_object(object_name)
        if target is None:
            raise RuntimeError(f"Object not found: {object_name}")
        material = Materials.Material()
        material.Name = "VibeCAD Appearance"
        material.addAppearanceModel(Materials.UUIDs().BasicRendering)
        material.setAppearanceValue(
            "DiffuseColor",
            f"({rgb[0]:.4f}, {rgb[1]:.4f}, {rgb[2]:.4f}, 1.0)",
        )
        material.setAppearanceValue("Transparency", str(alpha))
        target.ShapeMaterial = material
        doc.recompute()
        applied = target.ShapeMaterial
        return {
            "document": doc.Name,
            "object": target.Name,
            "label": getattr(target, "Label", target.Name),
            "type": getattr(target, "TypeId", ""),
            "material_name": getattr(applied, "Name", ""),
            "diffuse_color": applied.getAppearanceValue("DiffuseColor"),
            "transparency": float(applied.getAppearanceValue("Transparency")),
        }

    transaction = run_freecad_transaction(
        f"Apply material appearance to {object_name}",
        _apply,
    )
    return {"ok": bool(transaction.get("ok")), "transaction": transaction, "materials": domain_runtime.material_summary(service)}
