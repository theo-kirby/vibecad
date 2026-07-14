# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one persisted OpenSCAD source model."""

TOOL_SPEC = {
    "name": "openscad.create_model",
    "description": (
        "Create one new source-backed OpenSCAD component, compile it in the isolated "
        "OpenSCAD runtime, validate every resulting solid, and atomically add one "
        "generated Body per disconnected solid. Write coherent parametric source, "
        "not a disposable primitive approximation. Failed source remains persisted "
        "under the returned model id so it can be repaired with edit_source. Select "
        "exact_brep for analytic manufacturing geometry or faceted_brep deliberately "
        "for OpenSCAD operations that require tessellation; fidelity never changes "
        "automatically."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "model_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "description": "Unique human-readable component or subassembly label.",
            },
            "source": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000000,
                "description": "Complete initial UTF-8 OpenSCAD source for the intended physical geometry.",
            },
            "parameters": {
                "type": "object",
                "description": "JSON-safe named OpenSCAD overrides exposed through -D without rewriting source.",
                "additionalProperties": True,
            },
            "conversion_mode": {
                "type": "string",
                "enum": ["exact_brep", "faceted_brep"],
                "description": "Required output fidelity: exact analytic BREP or explicitly faceted BREP.",
            },
        },
        "required": ["model_name", "source", "parameters", "conversion_mode"],
        "additionalProperties": False,
    },
}

RUNNER_HANDLED = True
