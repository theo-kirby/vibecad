# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``cam.create_operation``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import cam_runtime


OPERATION_FACTORIES: dict[str, tuple[str, str]] = {
    "profile": ("Path.Op.Profile", "Profile"),
    "pocket": ("Path.Op.PocketShape", "Pocket"),
    "drill": ("Path.Op.Drilling", "Drilling"),
    "adaptive": ("Path.Op.Adaptive", "Adaptive"),
    "helix": ("Path.Op.Helix", "Helix"),
    "surface": ("Path.Op.Surface", "Surface"),
}

_OCL_REQUIRED = ("surface",)


TOOL_SPEC = {
    "description": (
        "Create a machining operation inside a CAM job. Supported operation "
        "types: profile (contour), pocket, drill, adaptive (trochoidal "
        "clearing), helix (circular hole milling), and surface (3D dropcutter "
        "over freeform geometry; requires the OpenCamLib runtime). The "
        "operation is bound to a tool controller and generates toolpath "
        "commands on recompute."
    ),
    "name": "cam.create_operation",
    "parameters": {
        "type": "object",
        "properties": {
            "operation_type": {
                "type": "string",
                "enum": sorted(OPERATION_FACTORIES.keys()),
                "description": "Kind of machining operation to create.",
            },
            "job_name": {
                "type": "string",
                "description": "Job name or label. Defaults to the first job in the document.",
            },
            "label": {
                "type": "string",
                "description": "Optional label for the operation object.",
            },
            "tool_controller": {
                "type": "string",
                "description": (
                    "Label or name of the tool controller to use. Defaults to "
                    "the job's first tool controller."
                ),
            },
            "base_object": {
                "type": "string",
                "description": (
                    "Optional model object providing base geometry. When "
                    "omitted most operations process the whole model."
                ),
            },
            "sub_elements": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional subelement names on the base object, e.g. "
                    "['Face6'] or ['Edge3', 'Edge4']."
                ),
            },
            "start_depth": {
                "type": "number",
                "description": "Optional explicit start depth (mm, absolute Z).",
            },
            "final_depth": {
                "type": "number",
                "description": "Optional explicit final depth (mm, absolute Z).",
            },
            "step_down": {
                "type": "number",
                "description": "Optional step-down per pass (mm).",
            },
            "properties": {
                "type": "object",
                "description": (
                    "Optional extra operation properties by exact property "
                    "name, e.g. {'Side': 'Outside', 'UseComp': false}. Unknown "
                    "names are reported back, not silently dropped."
                ),
            },
        },
        "required": ["operation_type"],
    },
    "safety": "SAFE_WRITE",
    "workbench": "CAMWorkbench",
}


def _opencamlib_available() -> bool:
    try:
        import ocl  # noqa: F401

        return True
    except ImportError:
        try:
            import opencamlib  # noqa: F401

            return True
        except ImportError:
            return False


def run(
    service,
    operation_type: str = "",
    job_name: str = "",
    label: str = "",
    tool_controller: str = "",
    base_object: str = "",
    sub_elements: list[str] | None = None,
    start_depth: float | None = None,
    final_depth: float | None = None,
    step_down: float | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    op_key = str(operation_type or "").strip().lower()
    if op_key not in OPERATION_FACTORIES:
        return {
            "ok": False,
            "error": (
                f"Unknown operation type: {operation_type!r}. Supported: "
                f"{', '.join(sorted(OPERATION_FACTORIES))}."
            ),
            "recoverable": True,
        }

    if op_key in _OCL_REQUIRED and not _opencamlib_available():
        return {
            "ok": False,
            "error": (
                f"Operation '{op_key}' requires the OpenCamLib runtime (python "
                "module 'ocl' / 'opencamlib'), which is not installed in this "
                "environment. Install it (e.g. the python3-opencamlib package) "
                "or use a 2.5D operation such as profile/pocket/adaptive."
            ),
            "recoverable": True,
        }

    job = service._get_cam_job(job_name or None)
    if job is None:
        return cam_runtime.no_job_error(job_name or None)

    controllers = cam_runtime.job_tool_controllers(job)
    if not controllers:
        return {
            "ok": False,
            "error": f"Job {job.Name} has no tool controllers.",
            "recoverable": True,
            "next_actions": [
                {
                    "tool": "cam.add_tool",
                    "why": "Add a tool controller before creating operations.",
                },
            ],
        }
    tc = None
    if tool_controller:
        wanted = str(tool_controller)
        for candidate in controllers:
            if wanted in (getattr(candidate, "Label", None), getattr(candidate, "Name", None)):
                tc = candidate
                break
        if tc is None:
            return {
                "ok": False,
                "error": f"Tool controller not found on job {job.Name}: {tool_controller}",
                "recoverable": True,
                "tool_controllers": [cam_runtime.tool_controller_summary(c) for c in controllers],
            }
    else:
        tc = controllers[0]

    base = None
    if base_object:
        base = service._get_document_object(base_object)
        if base is None:
            return {
                "ok": False,
                "error": f"Base object not found: {base_object}",
                "recoverable": True,
            }

    module_name, factory_label = OPERATION_FACTORIES[op_key]

    def _create_operation() -> dict[str, Any]:
        import FreeCAD as App
        from importlib import import_module

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")

        op_module = import_module(module_name)
        op = op_module.Create(factory_label, parentJob=job)
        if label:
            op.Label = str(label)
        op.ToolController = tc
        if base is not None:
            op.Base = [(base, list(sub_elements or []))]

        unknown_properties: list[str] = []
        for prop_name, prop_value in (properties or {}).items():
            if hasattr(op, str(prop_name)):
                setattr(op, str(prop_name), prop_value)
            else:
                unknown_properties.append(str(prop_name))

        for prop_name, value in (
            ("StartDepth", start_depth),
            ("FinalDepth", final_depth),
            ("StepDown", step_down),
        ):
            if value is not None and hasattr(op, prop_name):
                op.setExpression(prop_name, None)
                setattr(op, prop_name, float(value))

        doc.recompute()
        path = getattr(op, "Path", None)
        commands = list(getattr(path, "Commands", []) or [])
        return {
            "document": doc.Name,
            "operation": op.Name,
            "operation_label": getattr(op, "Label", op.Name),
            "command_count": len(commands),
            "unknown_properties": unknown_properties,
        }

    transaction = run_freecad_transaction(
        f"Create CAM {op_key} operation on {job.Name}",
        _create_operation,
    )
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "job": job.Name,
        "operation_type": op_key,
        "operation": result.get("operation"),
        "operation_label": result.get("operation_label"),
        "command_count": result.get("command_count", 0),
        "tool_controller": cam_runtime.tool_controller_summary(tc),
        "next_action": (
            "Run cam.validate_job to check the toolpath against the machine's "
            "limits, then cam.postprocess to emit G-code."
        ),
    }
    if result.get("unknown_properties"):
        response["unknown_properties"] = result["unknown_properties"]
        response["warning"] = (
            "Some property names were not recognized on this operation and "
            f"were skipped: {', '.join(result['unknown_properties'])}."
        )
    if response["ok"] and response["command_count"] == 0:
        response["warning"] = (
            "The operation generated no toolpath commands. Check base geometry, "
            "depths, and tool diameter."
        )
    if not response["ok"]:
        response["error"] = transaction.get("error") or "CAM operation creation failed."
        response["recoverable"] = True
    return response
