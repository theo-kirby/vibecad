# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``cam.add_tool``."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import cam_runtime


TOOL_SPEC = {
    "description": (
        "Add a tool controller (cutting tool + feeds/speeds) to a CAM job. "
        "Spindle speed is validated against the job's machine RPM limits at "
        "creation time. Operations reference tool controllers by label."
    ),
    "name": "cam.add_tool",
    "parameters": {
        "type": "object",
        "properties": {
            "job_name": {
                "type": "string",
                "description": "Job name or label. Defaults to the first job in the document.",
            },
            "label": {
                "type": "string",
                "description": "Tool controller label, e.g. 'TC: 6mm Endmill'.",
            },
            "tool_number": {
                "type": "integer",
                "description": "Tool number (T word). Defaults to the next free number.",
            },
            "tool_shape": {
                "type": "string",
                "description": (
                    "Tool bit shape id, e.g. 'endmill', 'ballend', 'chamfer', "
                    "'drill', 'v-bit'. Default 'endmill'."
                ),
            },
            "diameter": {
                "type": "number",
                "description": "Cutting diameter in mm.",
            },
            "spindle_speed": {
                "type": "number",
                "description": "Spindle speed in RPM. Validated against the machine's limits.",
            },
            "horiz_feed": {
                "type": "number",
                "description": "Horizontal cutting feed rate (mm/min).",
            },
            "vert_feed": {
                "type": "number",
                "description": "Vertical (plunge) feed rate (mm/min).",
            },
            "tool_length_offset": {
                "type": "integer",
                "description": (
                    "Explicit tool length offset register (H number). 0 uses the "
                    "tool number. Only emitted when the machine outputs offsets."
                ),
            },
        },
    },
    "safety": "SAFE_WRITE",
    "workbench": "CAMWorkbench",
}


def run(
    service,
    job_name: str = "",
    label: str = "",
    tool_number: int = 0,
    tool_shape: str = "endmill",
    diameter: float = 0.0,
    spindle_speed: float = 0.0,
    horiz_feed: float = 0.0,
    vert_feed: float = 0.0,
    tool_length_offset: int = 0,
) -> dict[str, Any]:
    job = service._get_cam_job(job_name or None)
    if job is None:
        return cam_runtime.no_job_error(job_name or None)

    machine = cam_runtime.resolve_machine(getattr(job, "Machine", "") or None)
    if machine is not None and spindle_speed and spindle_speed > 0:
        max_rpm = cam_runtime.max_toolhead_rpm(machine)
        if max_rpm is not None and float(spindle_speed) > max_rpm:
            return {
                "ok": False,
                "error": (
                    f"Requested spindle speed {float(spindle_speed):g} RPM exceeds "
                    f"machine '{getattr(machine, 'name', job.Machine)}' limit of "
                    f"{max_rpm:g} RPM."
                ),
                "recoverable": True,
                "machine_limits": cam_runtime.machine_summary(machine),
                "next_actions": [
                    {
                        "tool": "cam.add_tool",
                        "why": f"Retry with spindle_speed <= {max_rpm:g}.",
                    },
                ],
            }

    def _add_tool() -> dict[str, Any]:
        import FreeCAD as App
        import Path.Tool.Controller as PathToolController

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")

        number = int(tool_number) if tool_number else job.Proxy.nextToolNumber()
        tc_label = label or f"TC{number}"
        tool = None
        shape = str(tool_shape or "endmill").strip().lower()
        if shape and shape != "endmill":
            from Path.Tool.toolbit import ToolBit

            toolbit = ToolBit.from_shape_id(f"{shape}.fcstd")
            tool = toolbit.attach_to_doc(doc=doc)
            if getattr(tool, "ViewObject", None):
                tool.ViewObject.Visibility = False

        tc = PathToolController.Create(tc_label, tool=tool, toolNumber=number)
        tc.Label = tc_label
        job.Proxy.addToolController(tc)

        tool_obj = getattr(tc, "Tool", None)
        if diameter and tool_obj is not None and hasattr(tool_obj, "Diameter"):
            tool_obj.Diameter = float(diameter)
        if spindle_speed:
            tc.SpindleSpeed = float(spindle_speed)
        if horiz_feed:
            tc.HorizFeed = f"{float(horiz_feed)} mm/min"
        if vert_feed:
            tc.VertFeed = f"{float(vert_feed)} mm/min"
        if tool_length_offset and hasattr(tc, "ToolLengthOffset"):
            tc.ToolLengthOffset = int(tool_length_offset)
        doc.recompute()
        return {
            "document": doc.Name,
            "job": job.Name,
            "tool_controller": cam_runtime.tool_controller_summary(tc),
        }

    transaction = run_freecad_transaction(
        f"Add CAM tool controller to {job.Name}",
        _add_tool,
    )
    result = transaction.get("result") if isinstance(transaction.get("result"), dict) else {}
    response = {
        "ok": bool(transaction.get("ok")),
        "transaction": transaction,
        "job": result.get("job", job.Name),
        "tool_controller": result.get("tool_controller"),
        "tool_controllers": [
            cam_runtime.tool_controller_summary(tc) for tc in cam_runtime.job_tool_controllers(job)
        ],
        "next_action": (
            "Create machining operations with cam.create_operation referencing "
            "this tool controller."
        ),
    }
    if not response["ok"]:
        response["error"] = transaction.get("error") or "Adding CAM tool controller failed."
        response["recoverable"] = True
    return response
