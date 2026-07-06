# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native Sketcher open/edit sketch tool."""

from __future__ import annotations

from typing import Any

from .common import get_sketch, no_sketch, profile_validation, run_freecad_transaction, solver_status


TOOL_SPEC = {
    "name": "sketcher.open_sketch",
    "description": (
        "Open an existing native Sketcher sketch for editing and return current solver/profile "
        "state. Pair with sketcher.close_sketch before creating PartDesign features."
    ),
    "contextual": True,
    "parameters": {
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string",
                "description": "Sketch object name or label. Defaults to the first sketch.",
            },
        },
    },
}


def run(
    service: Any,
    sketch_name: str | None = None,
) -> dict[str, Any]:
    sketch = get_sketch(service, sketch_name)
    if sketch is None:
        return no_sketch(sketch_name)

    def _open() -> dict[str, Any]:
        import FreeCAD as App

        target = get_sketch(service, sketch.Name)
        if target is None:
            raise RuntimeError(f"Sketch not found: {sketch.Name}")
        edit_opened = False
        try:
            import FreeCADGui as Gui

            Gui.ActiveDocument.setEdit(target.Name)
            Gui.updateGui()
            edit_opened = True
        except Exception:
            edit_opened = False
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        return {
            "sketch": target.Name,
            "sketch_label": getattr(target, "Label", target.Name),
            "edit_opened": edit_opened,
            "active_workbench": service.active_workbench_name(),
            "sketcher": service.sketcher_summary(target.Name),
            "solver_status": solver_status(service, target),
            "profile_validation": profile_validation(service, target),
        }

    transaction = run_freecad_transaction("Open Sketcher sketch", _open)
    updated = get_sketch(service, sketch.Name)
    return {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "active_sketch": sketch.Name,
        "sketcher": service.sketcher_summary(sketch.Name),
        "solver_status": solver_status(service, updated),
        "profile_validation": profile_validation(service, updated),
        "next_actions": service._sketch_next_actions(updated),
    }
