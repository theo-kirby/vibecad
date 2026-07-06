# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``cam.create_job``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import cam_runtime, domain_runtime


TOOL_SPEC = {
    "description": (
        "Create a CAM job for one or more model objects. The job groups tool "
        "controllers, operations, and stock, and can be bound to a saved "
        "machine so cam.validate_job and cam.postprocess enforce its limits."
    ),
    "name": "cam.create_job",
    "parameters": {
        "type": "object",
        "properties": {
            "model_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Names or labels of the solid model objects to machine "
                    "(e.g. a PartDesign Body or Part primitive)."
                ),
            },
            "machine_name": {
                "type": "string",
                "description": (
                    "Display name of a saved machine (from cam.define_machine or "
                    "a built-in template) to bind to this job."
                ),
            },
            "label": {
                "type": "string",
                "description": "Optional label for the job object.",
            },
            "stock_extension": {
                "type": "number",
                "description": (
                    "Uniform stock margin (mm) added around the model bounding "
                    "box in X and Y and above it in Z. Default 1."
                ),
            },
        },
        "required": ["model_names"],
    },
    "safety": "SAFE_WRITE",
    "workbench": "CAMWorkbench",
}


def run(
    service,
    model_names: list[str] | None = None,
    machine_name: str = "",
    label: str = "",
    stock_extension: float = 1.0,
) -> dict[str, Any]:
    if not model_names:
        return {
            "ok": False,
            "error": "At least one model object name is required.",
            "recoverable": True,
        }

    models = []
    for model_name in model_names:
        obj = service._get_document_object(model_name)
        if obj is None:
            return {
                "ok": False,
                "error": f"Model object not found: {model_name}",
                "recoverable": True,
                "next_actions": [
                    {
                        "tool": "core.get_active_document",
                        "why": "Inspect document object names and labels before retrying.",
                    },
                ],
            }
        models.append(obj)

    machine = None
    if machine_name:
        machine = cam_runtime.resolve_machine(machine_name)
        if machine is None:
            return {
                "ok": False,
                "error": f"Machine not found: {machine_name}",
                "recoverable": True,
                "available_machines": cam_runtime.available_machine_names(),
                "next_actions": [
                    {
                        "tool": "cam.define_machine",
                        "why": "Define and save the machine before assigning it to a job.",
                    },
                ],
            }

    def _create_job() -> dict[str, Any]:
        import FreeCAD as App
        import Path.Main.Job as PathJob

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        job = PathJob.Create("Job", models, None)
        if label:
            job.Label = str(label)
        if machine is not None:
            job.Machine = getattr(machine, "name", str(machine_name))
        try:
            stock = getattr(job, "Stock", None)
            if stock is not None and hasattr(stock, "ExtXneg"):
                margin = float(stock_extension)
                stock.ExtXneg = margin
                stock.ExtXpos = margin
                stock.ExtYneg = margin
                stock.ExtYpos = margin
                stock.ExtZneg = 0.0
                stock.ExtZpos = margin
        except Exception:
            pass
        doc.recompute()
        return {
            "document": doc.Name,
            "job": job.Name,
            "job_label": getattr(job, "Label", job.Name),
            "machine": getattr(job, "Machine", "") or None,
            "stock": getattr(getattr(job, "Stock", None), "Name", None),
            "models": [m.Name for m in models],
        }

    transaction = run_freecad_transaction(
        f"Create CAM job for {', '.join(m.Name for m in models)}",
        _create_job,
    )
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "job": result.get("job"),
        "job_label": result.get("job_label"),
        "machine": result.get("machine"),
        "stock": result.get("stock"),
        "models": result.get("models", []),
        "cam_summary": domain_runtime.cam_summary(service, result.get("job")),
        "next_action": (
            "Add tool controllers with cam.add_tool, then machining operations "
            "with cam.create_operation."
        ),
    }
    if machine is not None:
        response["machine_limits"] = cam_runtime.machine_summary(machine)
    if not response["ok"]:
        response["error"] = transaction.get("error") or "CAM job creation failed."
        response["recoverable"] = True
    return response
