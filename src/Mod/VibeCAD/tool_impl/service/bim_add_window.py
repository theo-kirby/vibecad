# SPDX-License-Identifier: LGPL-2.1-or-later

"""Insert one native BIM window or door into an exact host wall."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "bim.add_window",
    "description": (
        "Insert one native BIM window or door into an exact host wall. The "
        "opening is cut through the wall automatically. The window plane is "
        "vertical; rotate it with rotation_z_degrees to match the wall "
        "direction (0 means the plane is parallel to the global X axis). "
        "Position is the bottom-left corner of the opening, so its Z sets "
        "the sill height."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "BIMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "host_wall": {
                "type": "string",
                "description": (
                    "Exact internal name of the wall to cut the opening "
                    "into, from bim.list_structure."
                ),
            },
            "preset": {
                "type": "string",
                "enum": ["fixed_window", "open_window", "door", "glass_door"],
                "description": (
                    "Opening kind: 'fixed_window' is a non-opening glazed "
                    "window, 'open_window' is a single-pane opening window, "
                    "'door' is a solid door, 'glass_door' is a glazed door. "
                    "Doors get IFC type Door, windows get Window."
                ),
            },
            "width_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Total opening width in mm.",
            },
            "height_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Total opening height in mm.",
            },
            "position": domain_runtime.vector_schema(
                "Global position of the opening's bottom-left corner in mm; "
                "Z is the sill/threshold height."
            ),
            "rotation_z_degrees": {
                "type": "number",
                "description": (
                    "Rotation of the window plane around the global Z axis "
                    "in degrees; 0 keeps the plane parallel to the global X "
                    "axis. Match the host wall's direction."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Visible label for the new window or door, e.g. 'FrontDoor'."
                ),
            },
        },
        "required": [
            "host_wall",
            "preset",
            "width_mm",
            "height_mm",
            "position",
            "rotation_z_degrees",
            "label",
        ],
        "additionalProperties": False,
    },
}

# Preset name plus frame parameters (h1 h2 h3 w1 w2 o1 o2) passed to
# Arch.makeWindowPreset. Frame values follow the BIM workbench test defaults.
_PRESETS = {
    "fixed_window": ("Fixed", 50.0, 50.0, 0.0, 100.0, 50.0, 0.0, 50.0),
    "open_window": ("Open 1-pane", 50.0, 50.0, 0.0, 100.0, 50.0, 0.0, 50.0),
    "door": ("Simple door", 50.0, 50.0, 0.0, 100.0, 40.0, 0.0, 0.0),
    "glass_door": ("Glass door", 50.0, 50.0, 0.0, 100.0, 40.0, 0.0, 0.0),
}


def run(
    service: Any,
    host_wall: str,
    preset: str,
    width_mm: float,
    height_mm: float,
    position: dict[str, Any],
    rotation_z_degrees: float,
    label: str,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    wall_name = str(host_wall or "").strip()
    if not wall_name:
        return _invalid("host_wall is required.")
    preset_spec = _PRESETS.get(str(preset or ""))
    if preset_spec is None:
        return _invalid(
            "preset must be fixed_window, open_window, door, or glass_door."
        )
    width = float(width_mm)
    height = float(height_mm)
    if width <= 0:
        return _invalid("width_mm must be greater than 0.")
    if height <= 0:
        return _invalid("height_mm must be greater than 0.")
    rotation_z = float(rotation_z_degrees)
    preset_name, h1, h2, h3, w1, w2, o1, o2 = preset_spec

    def create() -> dict[str, Any]:
        import Arch
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        wall = doc.getObject(wall_name)
        if wall is None:
            raise RuntimeError(
                f"Host wall '{wall_name}' not found; use bim.list_structure "
                "for exact names."
            )
        if getattr(getattr(wall, "Proxy", None), "Type", "") != "Wall":
            raise RuntimeError(
                f"Object '{wall_name}' is not a BIM wall; bim.add_window "
                "cuts openings only into walls from bim.create_wall."
            )
        # Stand the preset sketch upright, then rotate to the wall direction.
        rotation = App.Rotation(App.Vector(0, 0, 1), rotation_z).multiply(
            App.Rotation(App.Vector(1, 0, 0), 90)
        )
        placement = App.Placement(domain_runtime.parse_vector(position), rotation)
        window = Arch.makeWindowPreset(
            preset_name,
            width,
            height,
            h1,
            h2,
            h3,
            w1,
            w2,
            o1,
            o2,
            placement=placement,
        )
        if window is None:
            raise RuntimeError("Arch.makeWindowPreset did not create an object.")
        window.Label = clean_label
        window.Hosts = [wall]
        doc.recompute()
        return {
            "document": doc.Name,
            "feature": window.Name,
            "feature_label": window.Label,
            "feature_type": window.TypeId,
            "ifc_type": getattr(window, "IfcType", None),
            "host_wall": wall.Name,
            "preset": preset_name,
            "shape": domain_runtime.shape_summary(window),
            "feature_state": domain_runtime.feature_state_summary(window),
            "wall_state": domain_runtime.feature_state_summary(wall),
        }

    transaction = run_freecad_transaction(
        f"Add BIM window: {clean_label}",
        create,
    )
    return domain_runtime.part_feature_result(
        transaction,
        operation="add_window",
        next_action=(
            "Capture a screenshot to confirm the opening cuts the wall; a "
            "window floating outside the wall means position or rotation is "
            "wrong."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
