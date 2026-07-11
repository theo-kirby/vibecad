# SPDX-License-Identifier: LGPL-2.1-or-later

"""Create one native CAM job for exact shaped model objects."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {
    "name": "cam.create_job",
    "description": (
        "Create one native CAM job (Path::FeaturePython) machining exact "
        "shaped model objects. The job gets a stock body enlarged from the "
        "model bounding box by the given margins, plus empty Tools and "
        "Operations groups. Add a tool with cam.add_tool before adding "
        "operations with cam.add_operation."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "CAMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Visible label for the new CAM job.",
            },
            "model_object_names": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "string",
                    "description": (
                        "Exact internal name of one shaped object to machine."
                    ),
                },
                "description": (
                    "Exact internal names of the shaped model objects this "
                    "job machines; the job clones them, sources are unchanged."
                ),
            },
            "stock_margins_mm": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "number",
                        "minimum": 0,
                        "description": (
                            "Extra stock in mm added on both the negative "
                            "and positive X sides of the model bounding box."
                        ),
                    },
                    "y": {
                        "type": "number",
                        "minimum": 0,
                        "description": (
                            "Extra stock in mm added on both the negative "
                            "and positive Y sides of the model bounding box."
                        ),
                    },
                    "z": {
                        "type": "number",
                        "minimum": 0,
                        "description": (
                            "Extra stock in mm added on both the bottom and "
                            "top Z sides of the model bounding box."
                        ),
                    },
                },
                "required": ["x", "y", "z"],
                "additionalProperties": False,
                "description": (
                    "Stock allowance in mm beyond the model bounding box on "
                    "each axis; 1-2 mm is typical for milling from slightly "
                    "oversized blanks."
                ),
            },
        },
        "required": ["label", "model_object_names", "stock_margins_mm"],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    label: str,
    model_object_names: list[str],
    stock_margins_mm: dict[str, Any],
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    doc = service._active_document()
    if doc is None:
        return _invalid("No active document.")
    clean_names: list[str] = []
    for raw_name in model_object_names or []:
        name = str(raw_name or "").strip()
        if not name:
            return _invalid("model_object_names entries must be non-empty.")
        obj = doc.getObject(name)
        if obj is None:
            return _invalid(f"Object not found by exact internal name: {name}")
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            return _invalid(
                f"Object has no shape geometry to machine: {name}. "
                "CAM jobs need shaped BREP objects."
            )
        if name in clean_names:
            return _invalid(f"Duplicate model object: {name}")
        clean_names.append(name)
    if not clean_names:
        return _invalid("At least one model object is required.")
    try:
        import Path.Main.Job as PathJob
    except ImportError:
        return _invalid(
            "The CAM workbench is not available in this FreeCAD build; "
            "jobs cannot be created."
        )
    margins = {
        axis: float(stock_margins_mm.get(axis, 0) or 0) for axis in ("x", "y", "z")
    }

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        models = []
        for name in clean_names:
            model = active.getObject(name)
            if model is None:
                raise RuntimeError(f"Model object no longer exists: {name}")
            models.append(model)
        job = PathJob.Create("Job", models, None)
        job.Label = clean_label
        stock = getattr(job, "Stock", None)
        if stock is not None and hasattr(stock, "ExtXneg"):
            stock.ExtXneg = margins["x"]
            stock.ExtXpos = margins["x"]
            stock.ExtYneg = margins["y"]
            stock.ExtYpos = margins["y"]
            stock.ExtZneg = margins["z"]
            stock.ExtZpos = margins["z"]
        active.recompute()
        return {
            "document": active.Name,
            "job": job.Name,
            "job_label": job.Label,
            "models": clean_names,
            "stock": getattr(stock, "Name", None),
            "stock_margins_mm": margins,
        }

    transaction = run_freecad_transaction(
        f"Create CAM job: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "create_job"},
        next_action=(
            "Add a cutting tool with cam.add_tool, then machining "
            "operations with cam.add_operation."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
