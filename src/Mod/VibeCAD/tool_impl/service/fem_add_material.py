# SPDX-License-Identifier: LGPL-2.1-or-later

"""Add one solid material from the material library to an exact FEM analysis."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_SUMMARY_PROPERTIES = (
    "Density",
    "YoungsModulus",
    "PoissonRatio",
    "ThermalConductivity",
    "ThermalExpansionCoefficient",
    "SpecificHeat",
)


TOOL_SPEC = {
    "name": "fem.add_material",
    "description": (
        "Add one solid material to an exact FEM analysis from the material "
        "library by exact UUID (find UUIDs with material.list_materials). "
        "The solver reads mechanical values (Young's modulus, Poisson "
        "ratio, density) from this material; a solve without a material "
        "fails. One material covering the whole model is the common case."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "FemWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "analysis_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the FEM analysis from fem.list_analysis."
                ),
            },
            "material_uuid": {
                "type": "string",
                "description": (
                    "Exact UUID of the material card from "
                    "material.list_materials; pick a card with mechanical "
                    "properties (e.g. a steel or aluminium alloy) for "
                    "structural analyses."
                ),
            },
            "label": {
                "type": "string",
                "description": "Visible label for the new material object.",
            },
        },
        "required": ["analysis_name", "material_uuid", "label"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    analysis_name: str,
    material_uuid: str,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    clean_uuid = str(material_uuid or "").strip()
    if not clean_uuid:
        return _invalid("material_uuid is required.")
    analysis = service._get_fem_analysis(str(analysis_name or "").strip())
    if analysis is None:
        return _invalid(
            f"FEM analysis not found by exact internal name: {analysis_name}. "
            "Call fem.list_analysis for exact names."
        )
    try:
        import ObjectsFem
    except ImportError:
        return _invalid(
            "The FEM workbench is not available in this FreeCAD build; "
            "materials cannot be added."
        )
    try:
        import Materials
    except ImportError:
        return _invalid(
            "The Materials module is not available in this FreeCAD build; "
            "material cards cannot be read."
        )
    try:
        manager = Materials.MaterialManager()
        card = manager.getMaterial(clean_uuid)
    except Exception as exc:
        return _invalid(
            f"Material not found by UUID {clean_uuid}: {exc}. Use "
            "material.list_materials to find valid UUIDs."
        )
    if card is None:
        return _invalid(
            f"Material not found by UUID: {clean_uuid}. Use "
            "material.list_materials to find valid UUIDs."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        target = active.getObject(analysis.Name)
        if target is None:
            raise RuntimeError("The analysis no longer exists.")
        material_obj = ObjectsFem.makeMaterialSolid(active, "FemMaterial")
        material_obj.Label = clean_label
        material_obj.Material = dict(card.Properties)
        try:
            material_obj.UUID = clean_uuid
        except Exception:
            pass
        target.addObject(material_obj)
        active.recompute()
        properties = dict(card.Properties)
        return {
            "document": active.Name,
            "analysis": target.Name,
            "material_object": material_obj.Name,
            "material_object_label": material_obj.Label,
            "material_name": str(properties.get("Name", "")),
            "material_uuid": clean_uuid,
            "mechanical_properties": {
                name: str(properties[name])
                for name in _SUMMARY_PROPERTIES
                if name in properties
            },
        }

    transaction = run_freecad_transaction(
        f"Add FEM material: {clean_label}",
        create,
    )
    envelope = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "add_material"},
        next_action=(
            "Add constraints with fem.add_constraint (at least one fixed "
            "support and one load for a static analysis)."
        ),
    )
    result = transaction.get("result") if isinstance(transaction, dict) else None
    if envelope.get("ok") and isinstance(result, dict):
        mechanical = result.get("mechanical_properties") or {}
        if "YoungsModulus" not in mechanical:
            envelope["warning"] = (
                "The chosen material card defines no YoungsModulus; a "
                "structural solve will fail. Pick a card with mechanical "
                "properties via material.list_materials."
            )
    return envelope


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
