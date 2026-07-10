# SPDX-License-Identifier: LGPL-2.1-or-later

"""Capture a target-aware viewport image for provider visual inspection."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import re
import time
from typing import Any

from . import core_set_view


CAPTURE_FRAME_MODES = ("auto",) + core_set_view.FRAME_MODES
CAPTURE_ORIENTATIONS = ("auto",) + core_set_view.ALLOWED_ORIENTATIONS
CAPTURE_ANNOTATION_MODES = ("clean", "current")


TOOL_SPEC = {
    "description": (
        "Capture a viewport image for visual verification. auto frames an open sketch "
        "from its actual curves, otherwise the full model. clean removes Sketcher "
        "constraint labels, leaders, and support-circle graphics from the captured image "
        "without changing the sketch or the user's persistent display settings."
    ),
    "name": "core.capture_view_screenshot",
    "parameters": {
        "type": "object",
        "properties": {
            "orientation": {
                "type": "string",
                "enum": list(CAPTURE_ORIENTATIONS),
                "default": "auto",
            },
            "frame": {
                "type": "string",
                "enum": list(CAPTURE_FRAME_MODES),
                "default": "auto",
            },
            "object_names": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": "Exact internal names when frame is objects.",
            },
            "sketch_annotations": {
                "type": "string",
                "enum": list(CAPTURE_ANNOTATION_MODES),
                "default": "clean",
            },
        },
        "additionalProperties": False,
    },
    "safety": "VIEW",
}


def run(
    service: Any,
    orientation: str | None = None,
    frame: str = "auto",
    object_names: list[str] | None = None,
    sketch_annotations: str = "clean",
) -> dict[str, Any]:
    orientation_mode = str(orientation or "auto").strip().lower()
    frame_mode = str(frame or "auto").strip().lower()
    annotation_mode = str(sketch_annotations or "clean").strip().lower()
    if orientation_mode not in CAPTURE_ORIENTATIONS:
        return _remember_failure(
            service,
            f"Unknown orientation {orientation_mode!r}.",
            allowed_orientations=list(CAPTURE_ORIENTATIONS),
        )
    if frame_mode not in CAPTURE_FRAME_MODES:
        return _remember_failure(
            service,
            f"Unknown frame mode {frame_mode!r}.",
            allowed_frame_modes=list(CAPTURE_FRAME_MODES),
        )
    if annotation_mode not in CAPTURE_ANNOTATION_MODES:
        return _remember_failure(
            service,
            f"Unknown sketch_annotations mode {annotation_mode!r}.",
            allowed_sketch_annotation_modes=list(CAPTURE_ANNOTATION_MODES),
        )

    try:
        import FreeCAD as App
        import FreeCADGui as Gui
    except Exception as exc:
        return _remember_failure(service, str(exc))

    document = App.ActiveDocument
    if document is None:
        return _remember_failure(service, "No active document.")
    gui_document = getattr(Gui, "ActiveDocument", None)
    view = getattr(gui_document, "ActiveView", None) if gui_document else None
    if view is None:
        return _remember_failure(service, "No active 3D view is available.")

    active_sketch = service._get_sketch()
    resolved_frame = frame_mode
    if resolved_frame == "auto":
        resolved_frame = "active_sketch" if active_sketch is not None else "all"
    resolved_orientation = orientation_mode
    if resolved_orientation == "auto":
        resolved_orientation = "none" if active_sketch is not None else "isometric"

    frame_resolution = core_set_view.resolve_frame_objects(
        service,
        document,
        Gui,
        resolved_frame,
        object_names,
    )
    if not frame_resolution["ok"]:
        return _remember_failure(
            service,
            str(
                frame_resolution.get("error")
                or "Viewport target could not be resolved."
            ),
            **{
                key: value
                for key, value in frame_resolution.items()
                if key not in {"ok", "error"}
            },
        )
    frame_names = list(frame_resolution.get("object_names") or [])

    try:
        screenshot_dir = _screenshot_artifact_dir(service)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        document_name = _slug(document.Name or "view")
        path = screenshot_dir / f"{document_name}-{int(time.time() * 1000)}.png"

        annotations_excluded = False
        framing = {"framed": False, "method": "unchanged"}
        with ExitStack() as stack:
            if resolved_frame not in {"none", "all"}:
                stack.enter_context(
                    core_set_view.temporarily_isolate_objects(document, frame_names)
                )
            if annotation_mode == "clean" and active_sketch is not None:
                annotations_excluded = stack.enter_context(
                    core_set_view.temporarily_detach_sketch_annotations(view)
                )

            if resolved_orientation != "none":
                getattr(
                    view,
                    core_set_view.ORIENTATION_METHODS[resolved_orientation],
                )()
            if resolved_frame != "none":
                framing = core_set_view.frame_view(
                    service,
                    view,
                    document,
                    resolved_frame,
                    frame_names,
                    exclude_sketch_annotations=False,
                )
            view.redraw()
            Gui.updateGui()
            view.saveImage(str(path), 1280, 900, "White")
        view.redraw()
        Gui.updateGui()

        captured = path.exists()
        result = {
            "ok": captured,
            "captured": captured,
            "path": str(path) if captured else None,
            "file_size": path.stat().st_size if captured else 0,
            "size": [1280, 900],
            "format": "png",
            "background": "White",
            "orientation": resolved_orientation,
            "frame": resolved_frame,
            "framing": framing,
            "framed_objects": frame_names,
            "sketch_annotations": annotation_mode,
            "sketch_annotations_excluded": bool(annotations_excluded),
            "artifact_role": "visual_verification",
            "workbench": _active_workbench_name(Gui),
            "document": document.Name,
        }
        if captured:
            result["visual_observation"] = service._screenshot_visual_observation(path)
        else:
            result["error"] = "View saveImage did not create a file."
        service._last_view_screenshot = result
        return result
    except Exception as exc:
        return _remember_failure(service, str(exc))


def _remember_failure(service: Any, error: str, **details: Any) -> dict[str, Any]:
    result = {
        "ok": False,
        "captured": False,
        "path": None,
        "file_size": 0,
        "error": error,
        "retry_same_call": False,
        **details,
    }
    service._last_view_screenshot = result
    return result


def _active_workbench_name(gui: Any) -> str | None:
    workbench = gui.activeWorkbench()
    return workbench.name() if workbench else None


def _screenshot_artifact_dir(service: Any) -> Path:
    project_context = service.project_context()
    root = project_context.get("root") if isinstance(project_context, dict) else None
    if not root:
        raise RuntimeError("The active document has no VibeCAD project root.")
    return Path(str(root)).expanduser() / "screenshots"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return slug[:64] or "view"
