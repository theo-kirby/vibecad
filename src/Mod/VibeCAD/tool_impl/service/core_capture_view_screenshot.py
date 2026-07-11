# SPDX-License-Identifier: LGPL-2.1-or-later

"""Capture a target-aware viewport image for provider visual inspection."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from . import core_set_view


CAPTURE_FRAME_MODES = ("auto",) + core_set_view.FRAME_MODES
CAPTURE_ORIENTATIONS = ("auto",) + core_set_view.ALLOWED_ORIENTATIONS
CAPTURE_ANNOTATION_MODES = ("clean", "current")
DUPLICATE_VISUAL_DIFFERENCE_THRESHOLD = 0.005


TOOL_SPEC = {
    "description": (
        "Capture a viewport image for visual verification. frame='auto' frames an "
        "open sketch from its actual curves, otherwise the full model. "
        "sketch_annotations='clean' removes Sketcher constraint labels, B-spline "
        "information overlays, leaders, and internal alignment graphics from the "
        "captured image without changing the sketch or the user's persistent "
        "display settings."
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
        capture_width, capture_height = _capture_size(view)
        document_visual_fingerprint = _document_visual_fingerprint(document)
        previous_capture = (
            dict(service._last_view_screenshot)
            if isinstance(service._last_view_screenshot, dict)
            else None
        )

        annotations_excluded = False
        information_overlay_excluded = False
        internal_geometry_excluded = False
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
                information_overlay_excluded = stack.enter_context(
                    core_set_view.temporarily_detach_sketch_information_overlay(view)
                )
                internal_geometry_excluded = stack.enter_context(
                    core_set_view.temporarily_hide_sketch_internal_geometry(view)
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
            view.saveImage(str(path), capture_width, capture_height, "White")
        view.redraw()
        Gui.updateGui()

        captured = path.exists()
        visual_fingerprint = _pixel_fingerprint(path) if captured else None
        new_observation = True
        duplicate_of = None
        visual_difference = None
        if (
            captured
            and previous_capture is not None
            and previous_capture.get("captured")
            and previous_capture.get("document") == document.Name
            and previous_capture.get("document_visual_fingerprint")
            == document_visual_fingerprint
        ):
            previous_path = Path(str(previous_capture.get("path") or ""))
            if previous_path.is_file():
                visual_difference = _pixel_difference(path, previous_path)
                if (
                    visual_difference is not None
                    and visual_difference <= DUPLICATE_VISUAL_DIFFERENCE_THRESHOLD
                ):
                    path.unlink()
                    path = previous_path
                    new_observation = False
                    duplicate_of = str(previous_path)

        result_size = [capture_width, capture_height]
        if not new_observation and previous_capture is not None:
            prior_size = previous_capture.get("size")
            if isinstance(prior_size, list) and len(prior_size) == 2:
                result_size = list(prior_size)
        result = {
            "ok": captured,
            "captured": captured,
            "path": str(path) if captured else None,
            "file_size": path.stat().st_size if captured else 0,
            "size": result_size,
            "format": "png",
            "background": "White",
            "orientation": resolved_orientation,
            "frame": resolved_frame,
            "framing": framing,
            "framed_objects": frame_names,
            "sketch_annotations": annotation_mode,
            "sketch_annotations_excluded": bool(annotations_excluded),
            "sketch_information_overlay_excluded": bool(information_overlay_excluded),
            "sketch_internal_geometry_excluded": bool(internal_geometry_excluded),
            "artifact_role": "visual_verification",
            "workbench": _active_workbench_name(Gui),
            "document": document.Name,
            "visual_fingerprint": visual_fingerprint,
            "document_visual_fingerprint": document_visual_fingerprint,
            "new_observation": new_observation,
        }
        if visual_difference is not None:
            result["visual_difference_from_previous"] = visual_difference
        if duplicate_of:
            result.update(
                {
                    "duplicate_of": duplicate_of,
                    "observation_status": (
                        "The CAD scene is unchanged and the viewport is visually "
                        "indistinguishable from the previous capture. "
                        "No new visual evidence was produced; edit the model or change "
                        "the view before capturing again."
                    ),
                }
            )
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


def _capture_size(view: Any) -> tuple[int, int]:
    width, height = view.getSize()
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise RuntimeError("The active viewport has invalid dimensions.")
    scale = min(1280.0 / width, 900.0 / height)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _pixel_fingerprint(path: Path) -> str | None:
    try:
        try:
            from PySide import QtGui
        except Exception:
            from PySide6 import QtGui
        image = QtGui.QImage(str(path))
        if image.isNull():
            return None
        sample = image.scaled(96, 96)
        pixels = bytearray()
        for y in range(sample.height()):
            for x in range(sample.width()):
                color = QtGui.QColor(sample.pixel(x, y))
                pixels.extend((color.red(), color.green(), color.blue()))
        return hashlib.sha256(pixels).hexdigest()
    except Exception:
        return None


def _pixel_difference(first_path: Path, second_path: Path) -> float | None:
    try:
        try:
            from PySide import QtGui
        except Exception:
            from PySide6 import QtGui
        first = QtGui.QImage(str(first_path))
        second = QtGui.QImage(str(second_path))
        if first.isNull() or second.isNull():
            return None
        first = first.scaled(96, 96)
        second = second.scaled(96, 96)
        difference = 0
        samples = 0
        for y in range(96):
            for x in range(96):
                # The navigation cube animates independently of CAD/view state.
                if x >= 76 and y <= 24:
                    continue
                first_color = QtGui.QColor(first.pixel(x, y))
                second_color = QtGui.QColor(second.pixel(x, y))
                difference += abs(first_color.red() - second_color.red())
                difference += abs(first_color.green() - second_color.green())
                difference += abs(first_color.blue() - second_color.blue())
                samples += 3
        return round(difference / max(1, samples * 255), 8)
    except Exception:
        return None


def _document_visual_fingerprint(document: Any) -> str:
    records = []
    for obj in list(document.Objects):
        shape = getattr(obj, "Shape", None)
        shape_hash = None
        type_id = str(getattr(obj, "TypeId", "") or "")
        is_reference_geometry = type_id in {
            "PartDesign::Line",
            "PartDesign::Plane",
            "PartDesign::Point",
            "App::Line",
            "App::Plane",
            "App::Point",
        }
        try:
            if (
                not is_reference_geometry
                and shape is not None
                and not bool(shape.isNull())
            ):
                shape_hash = int(shape.hashCode())
        except Exception:
            shape_hash = None
        placement_method = getattr(obj, "getGlobalPlacement", None)
        try:
            placement = (
                placement_method()
                if callable(placement_method)
                else getattr(obj, "Placement", None)
            )
        except Exception:
            placement = getattr(obj, "Placement", None)
        view_object = getattr(obj, "ViewObject", None)
        records.append(
            {
                "name": str(obj.Name),
                "type": type_id,
                "shape_hash": shape_hash,
                "placement": (
                    [float(value) for value in placement.toMatrix().A]
                    if placement is not None
                    else None
                ),
                "visible": bool(view_object.Visibility)
                if view_object is not None
                else None,
                "display_mode": (
                    str(getattr(view_object, "DisplayMode", ""))
                    if view_object is not None
                    else None
                ),
                "transparency": (
                    float(getattr(view_object, "Transparency", 0.0))
                    if view_object is not None
                    else None
                ),
            }
        )
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _screenshot_artifact_dir(service: Any) -> Path:
    project_context = service.project_context()
    root = project_context.get("root") if isinstance(project_context, dict) else None
    if not root:
        raise RuntimeError("The active document has no VibeCAD project root.")
    return Path(str(root)).expanduser() / "screenshots"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return slug[:64] or "view"
