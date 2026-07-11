# SPDX-License-Identifier: LGPL-2.1-or-later

"""Apply one material card to one shaped document object."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_SUMMARY_PHYSICAL_PROPERTIES = (
    "Density",
    "YoungsModulus",
    "PoissonRatio",
    "ThermalConductivity",
)


TOOL_SPEC = {
    "name": "material.apply_material",
    "description": (
        "Apply one material card from the library to one shaped document "
        "object by exact material UUID. This sets the object's ShapeMaterial, "
        "which carries physical properties (density, elasticity) used by FEM "
        "and updates the rendered appearance when the card defines one. Find "
        "UUIDs with material.list_materials first."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "MaterialWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the shaped object (Part::Feature "
                    "or derived) to apply the material to."
                ),
            },
            "material_uuid": {
                "type": "string",
                "description": (
                    "Exact UUID of the material card, as returned by "
                    "material.list_materials."
                ),
            },
        },
        "required": ["object_name", "material_uuid"],
        "additionalProperties": False,
    },
}


def run(service: Any, object_name: str, material_uuid: str) -> dict[str, Any]:
    clean_name = str(object_name or "").strip()
    clean_uuid = str(material_uuid or "").strip()
    if not clean_uuid:
        return _invalid("material_uuid is required.")
    doc = service._active_document()
    obj = doc.getObject(clean_name) if doc is not None and clean_name else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {object_name}")
    if not hasattr(obj, "ShapeMaterial"):
        return _invalid(
            f"Object has no ShapeMaterial property (not a shaped Part "
            f"feature): {clean_name}. Materials apply to solid/shape objects, "
            "not groups, sketches, or spreadsheets."
        )
    try:
        import Materials
    except ImportError:
        return _invalid(
            "The Materials module is not available in this FreeCAD build; "
            "materials cannot be applied."
        )
    try:
        manager = Materials.MaterialManager()
        material = manager.getMaterial(clean_uuid)
    except Exception as exc:
        return _invalid(
            f"Material not found by UUID {clean_uuid}: {exc}. Use "
            "material.list_materials to find valid UUIDs."
        )
    if material is None:
        return _invalid(
            f"Material not found by UUID: {clean_uuid}. Use "
            "material.list_materials to find valid UUIDs."
        )

    def apply() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(clean_name)
        if target is None:
            raise RuntimeError("The object no longer exists.")
        target.ShapeMaterial = material
        active.recompute()
        return {
            "document": active.Name,
            "object": target.Name,
            "object_label": target.Label,
            "material_name": str(getattr(material, "Name", "")),
            "material_uuid": clean_uuid,
            "physical_properties": _physical_summary(material),
        }

    transaction = run_freecad_transaction(
        f"Apply material: {clean_name}",
        apply,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "apply_material"},
        next_action=(
            "Verify the appearance with core.capture_view_screenshot if the "
            "material card defines one; physical properties are now available "
            "to FEM."
        ),
    )


def _physical_summary(material: Any) -> dict[str, str]:
    summary: dict[str, str] = {}
    for name in _SUMMARY_PHYSICAL_PROPERTIES:
        try:
            if not material.hasPhysicalProperty(name):
                continue
            value = material.getPhysicalValue(name)
        except Exception:
            continue
        if value is None:
            continue
        user_string = getattr(value, "UserString", None)
        summary[name] = str(user_string) if user_string is not None else str(value)
    return summary


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
