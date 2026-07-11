# SPDX-License-Identifier: LGPL-2.1-or-later

"""Add one machining operation to an exact CAM job."""

from __future__ import annotations

from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


_FACE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "object_name": {
            "type": "string",
            "description": (
                "Exact internal name of the job's model object that owns the face."
            ),
        },
        "face_name": {
            "type": "string",
            "description": (
                "Exact face name, e.g. 'Face3' from part.find_subelements."
            ),
        },
    },
    "required": ["object_name", "face_name"],
    "additionalProperties": False,
}

_BOUNDARY_MAP = {
    "boundbox": "Boundbox",
    "stock": "Stock",
    "perimeter": "Perimeter",
}


TOOL_SPEC = {
    "name": "cam.add_operation",
    "description": (
        "Add one machining operation to an exact CAM job and generate its "
        "toolpath. The operation uses the job's most recent tool controller "
        "unless tool_controller_name says otherwise. Depths are absolute Z "
        "in the job coordinate system: start_depth_mm is where cutting "
        "begins (usually the stock top) and final_depth_mm is the deepest "
        "cut (usually the model bottom for through cuts)."
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
                "description": "Visible label for the new operation.",
            },
            "start_depth_mm": {
                "type": "number",
                "description": (
                    "Absolute Z in mm where cutting starts, usually the stock top face."
                ),
            },
            "final_depth_mm": {
                "type": "number",
                "description": (
                    "Absolute Z in mm of the deepest cut; must be below start_depth_mm."
                ),
            },
            "tool_controller_name": {
                "type": "string",
                "description": (
                    "Exact internal name of the tool controller to cut "
                    "with; omit to use the job's most recent controller."
                ),
            },
            "operation": {
                "description": "Machining strategy; choose exactly one variant.",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "profile",
                                "description": (
                                    "Contour cut around the model outline "
                                    "or around exact faces, with cutter "
                                    "radius compensation."
                                ),
                            },
                            "side": {
                                "type": "string",
                                "enum": ["outside", "inside"],
                                "description": (
                                    "Which side of the contour the tool "
                                    "cuts on: 'outside' for external "
                                    "profiles, 'inside' for cutouts."
                                ),
                            },
                            "step_down_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Depth of cut per pass in mm; typically "
                                    "half the tool diameter or less."
                                ),
                            },
                            "faces": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _FACE_ITEM_SCHEMA,
                                "description": (
                                    "Exact faces whose contours to profile; "
                                    "omit to profile the whole model outline."
                                ),
                            },
                        },
                        "required": ["type", "side", "step_down_mm"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "pocket",
                                "description": (
                                    "Clear all material inside closed "
                                    "pocket faces down to the pocket floor."
                                ),
                            },
                            "faces": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": _FACE_ITEM_SCHEMA,
                                "description": (
                                    "Exact pocket floor or wall faces that "
                                    "bound the material to clear."
                                ),
                            },
                            "step_down_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Depth of cut per pass in mm; typically "
                                    "half the tool diameter or less."
                                ),
                            },
                            "step_over_percent": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "description": (
                                    "Sideways overlap between adjacent "
                                    "passes as percent of tool diameter; "
                                    "40-60 is typical."
                                ),
                            },
                        },
                        "required": [
                            "type",
                            "faces",
                            "step_down_mm",
                            "step_over_percent",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "drilling",
                                "description": (
                                    "Drill every circular hole in the model "
                                    "that the operation auto-detects; use a "
                                    "drill tool."
                                ),
                            },
                            "peck_depth_mm": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Depth in mm drilled per peck before "
                                    "retracting to clear chips; 0 drills "
                                    "each hole in one plunge."
                                ),
                            },
                        },
                        "required": ["type", "peck_depth_mm"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {
                                "const": "face",
                                "description": (
                                    "Mill the top of the stock flat down to "
                                    "start of the model, e.g. to clean up "
                                    "a rough blank."
                                ),
                            },
                            "boundary": {
                                "type": "string",
                                "enum": sorted(_BOUNDARY_MAP),
                                "description": (
                                    "Area to face: 'boundbox' covers the "
                                    "model bounding box, 'stock' the whole "
                                    "stock top, 'perimeter' the model "
                                    "outline only."
                                ),
                            },
                            "step_down_mm": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Depth of cut per pass in mm; facing "
                                    "passes are usually shallow, 0.5-2 mm."
                                ),
                            },
                            "step_over_percent": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "description": (
                                    "Sideways overlap between adjacent "
                                    "passes as percent of tool diameter; "
                                    "40-60 is typical."
                                ),
                            },
                        },
                        "required": [
                            "type",
                            "boundary",
                            "step_down_mm",
                            "step_over_percent",
                        ],
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "required": [
            "job_name",
            "label",
            "start_depth_mm",
            "final_depth_mm",
            "operation",
        ],
        "additionalProperties": False,
    },
}


def run(
    service: Any,
    job_name: str,
    label: str,
    start_depth_mm: float,
    final_depth_mm: float,
    operation: dict[str, Any],
    tool_controller_name: str | None = None,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        return _invalid("label is required.")
    if not isinstance(operation, dict) or "type" not in operation:
        return _invalid(
            "operation must be an object with a 'type' of "
            "profile, pocket, drilling, or face."
        )
    op_type = str(operation.get("type") or "").strip()
    if op_type not in ("profile", "pocket", "drilling", "face"):
        return _invalid(
            f"Unknown operation type: {op_type}. "
            "Choose profile, pocket, drilling, or face."
        )
    if float(final_depth_mm) >= float(start_depth_mm):
        return _invalid(
            "final_depth_mm must be below start_depth_mm "
            f"(got start {start_depth_mm}, final {final_depth_mm})."
        )
    job = service._get_cam_job(str(job_name or "").strip() or None)
    if job is None:
        return _invalid(
            f"CAM job not found: {job_name}. Use cam.list_jobs for exact names."
        )
    controllers = list(getattr(getattr(job, "Tools", None), "Group", []) or [])
    if not controllers:
        return _invalid(
            "This job has no tool controller; add one with cam.add_tool first."
        )
    controller = None
    if tool_controller_name:
        wanted = str(tool_controller_name).strip()
        for candidate in controllers:
            if candidate.Name == wanted or getattr(candidate, "Label", None) == wanted:
                controller = candidate
                break
        if controller is None:
            return _invalid(
                f"Tool controller not found in this job: {tool_controller_name}. "
                f"Available: {[tc.Name for tc in controllers]}."
            )
    doc = service._active_document()
    face_refs, error = _validate_faces(doc, job, operation.get("faces"))
    if error:
        return _invalid(error)
    if op_type == "pocket" and not face_refs:
        return _invalid("A pocket operation needs at least one face reference.")
    try:
        create_op = _op_factory(op_type)
    except ImportError:
        return _invalid(
            "The CAM workbench is not available in this FreeCAD build; "
            "operations cannot be added."
        )

    def create() -> dict[str, Any]:
        import FreeCAD as App

        active = App.ActiveDocument
        if active is None:
            raise RuntimeError("No active document.")
        op_obj = create_op(clean_label, parentJob=job)
        op_obj.Label = clean_label
        if controller is not None:
            op_obj.ToolController = controller
        if face_refs:
            base: dict[str, list[str]] = {}
            for object_name, face_name in face_refs:
                base.setdefault(object_name, []).append(face_name)
            op_obj.Base = [
                (active.getObject(object_name), faces)
                for object_name, faces in base.items()
            ]
        for prop, value in (
            ("StartDepth", float(start_depth_mm)),
            ("FinalDepth", float(final_depth_mm)),
        ):
            _set_depth(op_obj, prop, value)
        if op_type in ("profile", "pocket", "face"):
            _set_depth(op_obj, "StepDown", float(operation["step_down_mm"]))
        if op_type == "profile":
            op_obj.Side = "Outside" if operation["side"] == "outside" else "Inside"
        if op_type in ("pocket", "face"):
            op_obj.StepOver = int(operation["step_over_percent"])
        if op_type == "face":
            op_obj.BoundaryShape = _BOUNDARY_MAP[operation["boundary"]]
        if op_type == "drilling":
            proxy = op_obj.Proxy
            if not face_refs and hasattr(proxy, "findAllHoles"):
                proxy.findAllHoles(op_obj)
            peck = float(operation.get("peck_depth_mm", 0) or 0)
            if hasattr(op_obj, "PeckEnabled"):
                op_obj.PeckEnabled = peck > 0
                if peck > 0:
                    op_obj.PeckDepth = f"{peck} mm"
        active.recompute()
        commands = list(getattr(getattr(op_obj, "Path", None), "Commands", []) or [])
        return {
            "document": active.Name,
            "job": job.Name,
            "operation_object": op_obj.Name,
            "operation_label": op_obj.Label,
            "operation_type": op_type,
            "tool_controller": getattr(
                getattr(op_obj, "ToolController", None), "Name", None
            ),
            "path_command_count": len(commands),
            "cycle_time": getattr(job, "CycleTime", None),
        }

    transaction = run_freecad_transaction(
        f"Add CAM operation: {clean_label}",
        create,
    )
    result = domain_runtime.build_mutation_result(
        transaction,
        extra={"operation": f"add_operation:{op_type}"},
    )
    command_count = transaction.get("result", {}).get("path_command_count")
    if result.get("ok") and not command_count:
        result["ok"] = False
        result["error"] = (
            "The operation was created but generated an empty toolpath. "
            "Common causes: depths outside the model (check start_depth_mm/"
            "final_depth_mm against part.measure), faces that do not bound "
            "machinable material, or a tool too large for the geometry. "
            "The operation was left in the document for inspection."
        )
    elif result.get("ok"):
        result["next_action"] = (
            "Verify the toolpath visually with a screenshot, then add the "
            "next operation. G-code postprocessing to a file is left to "
            "the user in the FreeCAD GUI."
        )
    return result


def _op_factory(op_type: str) -> Any:
    if op_type == "profile":
        import Path.Op.Profile as PathProfile

        return PathProfile.Create
    if op_type == "pocket":
        import Path.Op.PocketShape as PathPocket

        return PathPocket.Create
    if op_type == "drilling":
        import Path.Op.Drilling as PathDrilling

        return PathDrilling.Create
    import Path.Op.MillFace as PathMillFace

    return PathMillFace.Create


def _set_depth(op_obj: Any, prop: str, value_mm: float) -> None:
    if not hasattr(op_obj, prop):
        return
    try:
        op_obj.setExpression(prop, None)
    except Exception:
        pass
    setattr(op_obj, prop, f"{value_mm} mm")


def _validate_faces(
    doc: Any, job: Any, faces: Any
) -> tuple[list[tuple[str, str]], str | None]:
    if not faces:
        return [], None
    if doc is None:
        return [], "No active document."
    model_names = {
        getattr(model, "Name", "")
        for model in getattr(getattr(job, "Model", None), "Group", []) or []
    }
    refs: list[tuple[str, str]] = []
    for item in faces:
        object_name = str(item.get("object_name") or "").strip()
        face_name = str(item.get("face_name") or "").strip()
        obj = doc.getObject(object_name) if object_name else None
        if obj is None:
            return [], f"Object not found by exact internal name: {object_name}"
        if model_names and object_name not in model_names:
            return [], (
                f"Object {object_name} is not part of this job's model; "
                f"job models: {sorted(model_names)}. Reference the job's "
                "model clones, not the original objects."
            )
        if not face_name.startswith("Face"):
            return [], (
                f"Invalid face name: {face_name}. CAM base geometry must be "
                "faces, e.g. 'Face3' from part.find_subelements."
            )
        shape = getattr(obj, "Shape", None)
        try:
            element = shape.getElement(face_name) if shape is not None else None
        except Exception:
            element = None
        if element is None:
            return [], f"Face not found on {object_name}: {face_name}"
        refs.append((object_name, face_name))
    return refs, None


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
