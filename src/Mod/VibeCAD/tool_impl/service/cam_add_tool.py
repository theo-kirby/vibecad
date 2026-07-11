# SPDX-License-Identifier: LGPL-2.1-or-later

"""Add one cutting tool (tool bit + controller) to an exact CAM job."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_SHAPE_IDS = {
    "endmill": "endmill",
    "ballend": "ballend",
    "drill": "drill",
    "chamfer": "chamfer",
    "vbit": "v-bit",
}


TOOL_SPEC = {
    "name": "cam.add_tool",
    "description": (
        "Add one cutting tool to an exact CAM job: a native tool bit of the "
        "chosen shape plus a tool controller holding its number, feeds, and "
        "spindle speed. Every machining operation needs a tool controller, "
        "so add at least one tool before cam.add_operation."
    ),
    "contextual": True,
    "safety": "SAFE_WRITE",
    "workbench": "CAMWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "job_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the CAM job from cam.list_jobs."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Visible label for the tool controller, e.g. '6mm Endmill'."
                ),
            },
            "shape": {
                "type": "string",
                "enum": sorted(_SHAPE_IDS),
                "description": (
                    "Tool bit shape: 'endmill' for flat-bottom milling, "
                    "'ballend' for 3D contouring, 'drill' for holes, "
                    "'chamfer' for edge breaks, 'vbit' for engraving."
                ),
            },
            "diameter_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Cutting diameter of the tool in mm.",
            },
            "tool_number": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Tool number for tool changes in the machine's tool "
                    "table; must be unique within the job."
                ),
            },
            "spindle_rpm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Spindle speed in revolutions per minute.",
            },
            "horizontal_feed_mm_per_min": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": ("Feed rate in mm/min for horizontal cutting moves."),
            },
            "vertical_feed_mm_per_min": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Feed rate in mm/min for vertical plunge moves; "
                    "typically a third to half of the horizontal feed."
                ),
            },
        },
        "required": [
            "job_name",
            "label",
            "shape",
            "diameter_mm",
            "tool_number",
            "spindle_rpm",
            "horizontal_feed_mm_per_min",
            "vertical_feed_mm_per_min",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    job_name: str,
    label: str,
    shape: str,
    diameter_mm: float,
    tool_number: int,
    spindle_rpm: float,
    horizontal_feed_mm_per_min: float,
    vertical_feed_mm_per_min: float,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    shape_id = _SHAPE_IDS.get(str(shape or "").strip())
    if shape_id is None:
        return _invalid(
            f"Unknown shape: {shape}. Choose one of: {', '.join(sorted(_SHAPE_IDS))}."
        )
    job = service._get_cam_job(str(job_name or "").strip() or None)
    if job is None:
        return _invalid(
            f"CAM job not found: {job_name}. Use cam.list_jobs for exact names."
        )
    existing_numbers = [
        int(getattr(tc, "ToolNumber", 0))
        for tc in getattr(getattr(job, "Tools", None), "Group", []) or []
    ]
    if int(tool_number) in existing_numbers:
        return _invalid(
            f"Tool number {tool_number} is already used in this job; "
            f"existing numbers: {sorted(existing_numbers)}."
        )
    try:
        import Path.Tool.Controller as PathController
        from Path.Tool.toolbit import ToolBit
    except ImportError:
        return _invalid(
            "The CAM workbench is not available in this FreeCAD build; "
            "tools cannot be added."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        toolbit = ToolBit.from_shape_id(shape_id, clean_label)
        tool_obj = toolbit.attach_to_doc(doc=active)
        if tool_obj.ViewObject:
            tool_obj.ViewObject.Visibility = False
        if hasattr(tool_obj, "Diameter"):
            tool_obj.Diameter = f"{float(diameter_mm)} mm"
        controller = PathController.Create(
            clean_label,
            tool=tool_obj,
            toolNumber=int(tool_number),
            assignViewProvider=bool(App.GuiUp),
        )
        controller.Label = clean_label
        controller.SpindleSpeed = float(spindle_rpm)
        controller.HorizFeed = f"{float(horizontal_feed_mm_per_min)} mm/min"
        controller.VertFeed = f"{float(vertical_feed_mm_per_min)} mm/min"
        job.Proxy.addToolController(controller)
        active.recompute()
        return {
            "document": active.Name,
            "job": job.Name,
            "tool_controller": controller.Name,
            "tool_controller_label": controller.Label,
            "tool_bit": tool_obj.Name,
            "shape": shape,
            "diameter_mm": float(diameter_mm),
            "tool_number": int(tool_number),
        }

    transaction = run_freecad_transaction(
        f"Add CAM tool: {clean_label}",
        create,
    )
    return domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": "add_tool"},
        next_action=(
            "Add machining operations with cam.add_operation; they pick up "
            "this tool controller automatically."
        ),
    )


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
