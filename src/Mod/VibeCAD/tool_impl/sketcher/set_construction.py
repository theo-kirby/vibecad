# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher construction-geometry toggle tool."""

from __future__ import annotations

from typing import Any

from .common import (
    active_response,
    get_sketch,
    resolve_geometry_index,
    run_freecad_transaction,
    validate_geometry_index,
)


TOOL_SPEC = {
    "name": "sketcher.set_construction",
    "safety": "SAFE_WRITE",
    "edit_modes": ["sketch"],
    "description": (
        "Set one Sketcher geometry element as construction or normal geometry, equivalent to "
        "toggling construction mode. Construction geometry guides constraints (axes, pitch "
        "circles) but is excluded from solid-feature profiles."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "geometry_index": {
                "type": "integer",
                "description": "Target geometry index.",
            },
            "geometry_handle": {
                "type": "string",
                "description": "Geometry handle (geometry:N / name:X) alternative to geometry_index.",
            },
            "construction": {
                "type": "boolean",
                "description": "True for construction geometry, false for normal profile geometry.",
            },
        },
        "required": ["construction"],
        "additionalProperties": False,
    },
}


def _invalid_call(error: str, **extra: Any) -> dict[str, Any]:
    result = {
        "ok": False,
        "error": error,
        "retry_same_call": False,
        "recoverable": True,
    }
    result.update(extra)
    return result


def run(
    service: Any,
    sketch_name: str | None = None,
    geometry_index: int | None = None,
    geometry_handle: str | None = None,
    construction: bool | None = None,
) -> dict[str, Any]:
    if construction is None or not isinstance(construction, bool):
        return _invalid_call(
            "sketcher.set_construction requires construction as an explicit boolean."
        )
    if geometry_index is None and not str(geometry_handle or "").strip():
        return _invalid_call(
            "sketcher.set_construction requires geometry_index or geometry_handle."
        )
    sketch = get_sketch(service)
    if sketch is None:
        return _invalid_call("No Sketcher sketch is currently open for editing.")
    try:
        index = resolve_geometry_index(service, sketch, geometry_index, geometry_handle)
    except Exception as exc:
        return _invalid_call(
            str(exc),
            geometry_index=geometry_index,
            geometry_handle=geometry_handle,
        )
    invalid = validate_geometry_index(sketch, index)
    if invalid:
        invalid.setdefault("retry_same_call", False)
        invalid.setdefault("recoverable", True)
        return invalid

    def _set() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        before = bool(target.getConstruction(index))
        target.setConstruction(index, bool(construction))
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        after = bool(target.getConstruction(index))
        geometry = service._geometry_summary(
            list(getattr(target, "Geometry", []))[index],
            index,
            target,
        )
        return {
            "sketch": target.Name,
            "geometry_index": index,
            "geometry_handle": geometry_handle or f"geometry:{index}",
            "before": before,
            "after": after,
            "before_construction": before,
            "after_construction": after,
            "changed": before != after,
            "geometry": geometry,
            "profile_effect": (
                "ignored_by_profile_validation"
                if after
                else "included_in_profile_validation"
            ),
            "modified_geometry_indices": [index],
        }

    return active_response(
        service,
        sketch,
        run_freecad_transaction("Set Sketcher construction geometry", _set),
    )
