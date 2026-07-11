# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create the BIM spatial skeleton: one site, one building, named levels."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "bim.create_spatial_structure",
    "description": (
        "Create the native BIM spatial skeleton in one call: a Site containing "
        "a Building containing one level (building storey) per entry, each "
        "placed at its exact elevation. Create this structure before walls so "
        "elements can be assigned to levels; add elements to a level via the "
        "level_object parameter of bim.create_wall and bim.create_structure."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "BIMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "site_label": {
                "type": "string",
                "description": "Visible label for the new site, e.g. 'MainSite'.",
            },
            "building_label": {
                "type": "string",
                "description": (
                    "Visible label for the new building, e.g. 'BuildingA'."
                ),
            },
            "levels": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "description": (
                    "Ordered levels (building storeys) to create inside the "
                    "building, lowest first."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                "Visible label for this level, e.g. 'GroundFloor'."
                            ),
                        },
                        "elevation_mm": {
                            "type": "number",
                            "description": (
                                "Global Z elevation of this level's (0,0,0) "
                                "point in mm; negative for basements."
                            ),
                        },
                    },
                    "required": ["label", "elevation_mm"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["site_label", "building_label", "levels"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    site_label: str,
    building_label: str,
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    clean_site = str(site_label or "").strip()
    clean_building = str(building_label or "").strip()
    if not clean_site:
        return _invalid("site_label is required.")
    if not clean_building:
        return _invalid("building_label is required.")
    if not isinstance(levels, list) or not levels:
        return _invalid("levels must contain at least one level.")
    level_specs: list[tuple[str, float]] = []
    for index, spec in enumerate(levels):
        if not isinstance(spec, dict):
            return _invalid(f"levels[{index}] must be an object.")
        label = str(spec.get("label") or "").strip()
        if not label:
            return _invalid(f"levels[{index}].label is required.")
        level_specs.append((label, float(spec.get("elevation_mm") or 0.0)))
    seen = set()
    for label, _elevation in level_specs:
        if label in seen:
            return _invalid(f"Duplicate level label: '{label}'.")
        seen.add(label)

    def create() -> dict[str, Any]:
        import Arch
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        level_objects = []
        level_summaries = []
        for label, elevation in level_specs:
            level = Arch.makeFloor(name=label)
            if level is None:
                raise RuntimeError(f"Arch.makeFloor did not create level '{label}'.")
            level.Placement = App.Placement(
                App.Vector(0.0, 0.0, elevation), App.Rotation()
            )
            level_objects.append(level)
            level_summaries.append(
                {
                    "object_name": level.Name,
                    "label": level.Label,
                    "elevation_mm": elevation,
                }
            )
        building = Arch.makeBuilding(level_objects, name=clean_building)
        if building is None:
            raise RuntimeError("Arch.makeBuilding did not create an object.")
        site = Arch.makeSite([building], name=clean_site)
        if site is None:
            raise RuntimeError("Arch.makeSite did not create an object.")
        doc.recompute()
        return {
            "document": doc.Name,
            "site": {"object_name": site.Name, "label": site.Label},
            "building": {"object_name": building.Name, "label": building.Label},
            "levels": level_summaries,
        }

    transaction = run_freecad_transaction(
        f"Create BIM spatial structure: {clean_site}",
        create,
    )
    result = (
        transaction.get("result", {})
        if isinstance(transaction, dict) and isinstance(transaction.get("result"), dict)
        else {}
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "create_spatial_structure", **result},
        next_action=(
            "Draw wall baselines with draft.create_wire, then create walls "
            "with bim.create_wall assigned to the new levels."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
