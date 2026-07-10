# SPDX-License-Identifier: LGPL-2.1-or-later

"""Target-aware viewport control for visual CAD inspection."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


ORIENTATION_METHODS = {
    "front": "viewFront",
    "top": "viewTop",
    "right": "viewRight",
    "rear": "viewRear",
    "bottom": "viewBottom",
    "left": "viewLeft",
    "isometric": "viewIsometric",
    "axometric": "viewAxometric",
}

ALLOWED_ORIENTATIONS = tuple(ORIENTATION_METHODS) + ("none",)
FRAME_MODES = ("none", "all", "active_sketch", "selection", "objects")
SKETCH_ANNOTATION_MODES = ("unchanged", "show", "hide")


TOOL_SPEC = {
    "description": (
        "Frame an exact CAD target, adjust zoom, control Sketcher annotations, or change "
        "object visibility in the active viewport. active_sketch framing uses the real "
        "curve extents rather than remote arc centers or constraint labels. Object names "
        "must be exact internal names from current CAD state."
    ),
    "name": "core.set_view",
    "parameters": {
        "type": "object",
        "properties": {
            "orientation": {
                "type": "string",
                "enum": list(ALLOWED_ORIENTATIONS),
                "default": "none",
            },
            "frame": {
                "type": "string",
                "enum": list(FRAME_MODES),
                "default": "none",
                "description": (
                    "Center and fit the whole scene, active sketch, current selection, "
                    "or object_names."
                ),
            },
            "object_names": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": "Exact objects to frame when frame is objects.",
            },
            "zoom_steps": {
                "type": "integer",
                "minimum": -12,
                "maximum": 12,
                "default": 0,
                "description": "Positive zooms in; negative zooms out after framing.",
            },
            "sketch_annotations": {
                "type": "string",
                "enum": list(SKETCH_ANNOTATION_MODES),
                "default": "unchanged",
                "description": (
                    "Show or hide Sketcher constraint icons, dimensions, leaders, and "
                    "support-circle graphics without changing the sketch."
                ),
            },
            "show_objects": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": "Exact internal object names to make visible.",
            },
            "hide_objects": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": "Exact internal object names to hide.",
            },
        },
        "additionalProperties": False,
    },
    "safety": "VIEW",
}


def run(
    service: Any,
    orientation: str | None = None,
    frame: str = "none",
    object_names: list[str] | None = None,
    zoom_steps: int = 0,
    sketch_annotations: str = "unchanged",
    show_objects: list[str] | None = None,
    hide_objects: list[str] | None = None,
) -> dict[str, Any]:
    orientation_name = str(orientation or "none").strip().lower()
    frame_mode = str(frame or "none").strip().lower()
    annotation_mode = str(sketch_annotations or "unchanged").strip().lower()
    if orientation_name not in ALLOWED_ORIENTATIONS:
        return _invalid(
            f"Unknown orientation {orientation_name!r}.",
            allowed_orientations=list(ALLOWED_ORIENTATIONS),
        )
    if frame_mode not in FRAME_MODES:
        return _invalid(
            f"Unknown frame mode {frame_mode!r}.",
            allowed_frame_modes=list(FRAME_MODES),
        )
    if annotation_mode not in SKETCH_ANNOTATION_MODES:
        return _invalid(
            f"Unknown sketch_annotations mode {annotation_mode!r}.",
            allowed_sketch_annotation_modes=list(SKETCH_ANNOTATION_MODES),
        )
    if isinstance(zoom_steps, bool) or not isinstance(zoom_steps, int):
        return _invalid("zoom_steps must be an integer from -12 through 12.")
    if zoom_steps < -12 or zoom_steps > 12:
        return _invalid("zoom_steps must be from -12 through 12.")

    try:
        import FreeCAD as App
        import FreeCADGui as Gui
    except Exception as exc:
        return _invalid(str(exc))

    document = App.ActiveDocument
    if document is None:
        return _invalid("No active document.")
    gui_document = getattr(Gui, "ActiveDocument", None)
    view = getattr(gui_document, "ActiveView", None) if gui_document else None
    if view is None:
        return _invalid("No active 3D view is available.")

    visibility = _resolve_visibility(document, show_objects, hide_objects)
    if not visibility["ok"]:
        return visibility
    frame_resolution = resolve_frame_objects(
        service,
        document,
        Gui,
        frame_mode,
        object_names,
    )
    if not frame_resolution["ok"]:
        return frame_resolution

    try:
        visibility_result = _apply_visibility(visibility["changes"])
        oriented = False
        if orientation_name != "none":
            getattr(view, ORIENTATION_METHODS[orientation_name])()
            oriented = True

        annotation_result = set_sketch_annotations(view, annotation_mode)
        frame_names = list(frame_resolution.get("object_names") or [])
        framing = frame_view(
            service,
            view,
            document,
            frame_mode,
            frame_names,
            exclude_sketch_annotations=(frame_mode == "active_sketch"),
        )
        zoomed = apply_zoom(view, zoom_steps)
        Gui.updateGui()
    except Exception as exc:
        return _invalid(str(exc))

    return {
        "ok": True,
        "document": document.Name,
        "orientation": orientation_name,
        "oriented": oriented,
        "frame": frame_mode,
        "framed": bool(framing.get("framed")),
        "framing": framing,
        "framed_objects": frame_names,
        "zoom_steps": zoomed,
        "sketch_annotations": annotation_result,
        "shown": visibility_result["shown"],
        "hidden": visibility_result["hidden"],
    }


def resolve_frame_objects(
    service: Any,
    document: Any,
    gui: Any,
    frame_mode: str,
    object_names: list[str] | None,
) -> dict[str, Any]:
    if frame_mode in {"none", "all"}:
        if object_names:
            return _invalid("object_names requires frame='objects'.")
        return {"ok": True, "object_names": []}

    if frame_mode == "active_sketch":
        sketch = service._get_sketch()
        if sketch is None:
            return _invalid(
                "No sketch is open for editing; active_sketch framing has no target."
            )
        return {"ok": True, "object_names": [sketch.Name]}

    if frame_mode == "selection":
        selected = [
            item
            for item in list(gui.Selection.getSelection() or [])
            if getattr(item, "Document", None) is document
        ]
        names = _unique_names(selected)
        if not names:
            return _invalid("The active document selection is empty.")
        return {"ok": True, "object_names": names}

    names = [str(name or "").strip() for name in list(object_names or [])]
    names = [name for name in names if name]
    if not names:
        return _invalid("object_names is required when frame='objects'.")
    objects = []
    missing = []
    for name in names:
        obj = document.getObject(name)
        if obj is None:
            missing.append(name)
        else:
            objects.append(obj)
    if missing:
        return _invalid(
            "Objects not found by exact internal name: " + ", ".join(missing),
            missing_objects=missing,
        )
    return {"ok": True, "object_names": _unique_names(objects)}


def frame_view(
    service: Any,
    view: Any,
    document: Any,
    frame_mode: str,
    object_names: list[str],
    *,
    exclude_sketch_annotations: bool = False,
) -> dict[str, Any]:
    if frame_mode == "none":
        return {"framed": False, "method": "unchanged"}
    if frame_mode == "all":
        view.fitAll()
        return {"framed": True, "method": "scene_fit_all"}
    if frame_mode == "active_sketch":
        sketch = service._get_sketch()
        if sketch is None:
            raise RuntimeError("No sketch is open for active_sketch framing.")
        return frame_active_sketch(view, sketch)

    with temporarily_isolate_objects(document, object_names):
        if exclude_sketch_annotations:
            with temporarily_detach_sketch_annotations(view):
                view.fitAll()
        else:
            view.fitAll()
    return {
        "framed": True,
        "method": "isolated_scene_fit",
        "object_names": list(object_names),
    }


def frame_active_sketch(view: Any, sketch: Any) -> dict[str, Any]:
    import FreeCAD as App

    points, local_bounds, geometry_scope = _sketch_curve_world_points(sketch)
    direction = view.getViewDirection()
    up = view.getUpDirection()
    direction_length = float(direction.Length)
    up_length = float(up.Length)
    if direction_length <= 1e-12 or up_length <= 1e-12:
        raise RuntimeError("The active camera has an invalid view or up direction.")
    direction = direction / direction_length
    up = up / up_length
    right = direction.cross(up)
    right_length = float(right.Length)
    if right_length <= 1e-12:
        raise RuntimeError("The active camera view and up directions are parallel.")
    right = right / right_length
    up = right.cross(direction)
    up = up / float(up.Length)

    right_coordinates = [float(point.dot(right)) for point in points]
    up_coordinates = [float(point.dot(up)) for point in points]
    width = max(right_coordinates) - min(right_coordinates)
    height = max(up_coordinates) - min(up_coordinates)
    viewport_width, viewport_height = view.getSize()
    if int(viewport_width) <= 0 or int(viewport_height) <= 0:
        raise RuntimeError("The active viewport has invalid dimensions.")
    aspect = float(viewport_width) / float(viewport_height)
    camera_height = max(height, width / aspect, 1.0) * 1.15

    center = App.Vector()
    for point in points:
        center = center + point
    center = center / len(points)

    camera = view.getCameraNode()
    if not hasattr(camera, "height"):
        raise RuntimeError(
            "Active-sketch framing requires FreeCAD's orthographic Sketcher camera."
        )
    focal_distance = float(camera.focalDistance.getValue())
    position = center - direction * focal_distance
    camera.position.setValue(float(position.x), float(position.y), float(position.z))
    camera.height.setValue(float(camera_height))
    view.redraw()
    return {
        "framed": True,
        "method": "actual_sketch_curve_bounds",
        "sketch": sketch.Name,
        "geometry_scope": geometry_scope,
        "local_bounds": local_bounds,
        "camera_height": camera_height,
        "projected_size": [width, height],
    }


def _sketch_curve_world_points(
    sketch: Any,
) -> tuple[list[Any], dict[str, list[float]], str]:
    import FreeCAD as App

    geometry = list(getattr(sketch, "Geometry", []) or [])
    defining_indices = [
        index
        for index in range(len(geometry))
        if not bool(sketch.getConstruction(index))
    ]
    geometry_scope = "defining_geometry"
    indices = defining_indices
    if not indices:
        indices = list(range(len(geometry)))
        geometry_scope = "construction_geometry"
    if not indices:
        raise RuntimeError(f"Sketch {sketch.Name} has no geometry to frame.")

    minimum = [float("inf"), float("inf"), float("inf")]
    maximum = [float("-inf"), float("-inf"), float("-inf")]
    for index in indices:
        shape = geometry[index].toShape()
        if shape is None or bool(shape.isNull()):
            raise RuntimeError(
                f"Sketch geometry:{index} produced a null shape during framing."
            )
        bounds = shape.BoundBox
        values_min = [float(bounds.XMin), float(bounds.YMin), float(bounds.ZMin)]
        values_max = [float(bounds.XMax), float(bounds.YMax), float(bounds.ZMax)]
        for axis in range(3):
            minimum[axis] = min(minimum[axis], values_min[axis])
            maximum[axis] = max(maximum[axis], values_max[axis])

    placement = sketch.getGlobalPlacement()
    points = []
    for x in (minimum[0], maximum[0]):
        for y in (minimum[1], maximum[1]):
            for z in (minimum[2], maximum[2]):
                points.append(placement.multVec(App.Vector(x, y, z)))
    return (
        points,
        {
            "min": minimum,
            "max": maximum,
            "size": [maximum[axis] - minimum[axis] for axis in range(3)],
        },
        geometry_scope,
    )


def apply_zoom(view: Any, zoom_steps: int) -> int:
    if zoom_steps == 0:
        return 0
    method = view.zoomIn if zoom_steps > 0 else view.zoomOut
    for _ in range(abs(zoom_steps)):
        method()
    return zoom_steps


def set_sketch_annotations(view: Any, mode: str) -> dict[str, Any]:
    if mode == "unchanged":
        return {"mode": mode, "changed": False}
    node = _constraint_group_node(view)
    if node is None:
        return {
            "mode": mode,
            "changed": False,
            "constraint_count": 0,
        }
    enabled = mode == "show"
    count = int(node.enable.getNum())
    for index in range(count):
        node.enable.set1Value(index, enabled)
    return {
        "mode": mode,
        "changed": True,
        "constraint_count": count,
    }


@contextmanager
def temporarily_isolate_objects(
    document: Any,
    object_names: list[str],
) -> Iterator[None]:
    keep = set(object_names)
    snapshots: list[tuple[Any, bool]] = []
    for obj in list(document.Objects):
        view_object = getattr(obj, "ViewObject", None)
        if view_object is None:
            continue
        visible = bool(view_object.Visibility)
        snapshots.append((view_object, visible))
        desired = obj.Name in keep
        if visible != desired:
            view_object.Visibility = desired
    try:
        yield
    finally:
        for view_object, visible in snapshots:
            view_object.Visibility = visible


@contextmanager
def temporarily_detach_sketch_annotations(view: Any) -> Iterator[bool]:
    search, path = _constraint_group_path(view)
    if path is None:
        yield False
        return
    if int(path.getLength()) < 2:
        raise RuntimeError("Sketcher ConstraintGroup has no scene-graph parent.")
    node = path.getTail()
    parent = path.getNodeFromTail(1)
    child_index = int(parent.findChild(node))
    if child_index < 0:
        raise RuntimeError("Sketcher ConstraintGroup is detached from its parent.")
    node.ref()
    parent.removeChild(child_index)
    try:
        yield True
    finally:
        parent.insertChild(node, child_index)
        node.unref()


def _constraint_group_node(view: Any) -> Any | None:
    search, path = _constraint_group_path(view)
    return path.getTail() if path is not None else None


def _constraint_group_path(view: Any) -> tuple[Any, Any | None]:
    from pivy import coin

    search = coin.SoSearchAction()
    search.setName("ConstraintGroup")
    search.setInterest(coin.SoSearchAction.FIRST)
    search.apply(view.getSceneGraph())
    return search, search.getPath()


def _resolve_visibility(
    document: Any, show_objects: Any, hide_objects: Any
) -> dict[str, Any]:
    changes = []
    missing = []
    seen = set()
    for names, visible in ((show_objects, True), (hide_objects, False)):
        for raw_name in list(names or []):
            name = str(raw_name).strip()
            if name in seen:
                return _invalid(f"Object {name} appears in both visibility lists.")
            seen.add(name)
            obj = document.getObject(name)
            if obj is None:
                missing.append(name)
                continue
            if getattr(obj, "ViewObject", None) is None:
                return _invalid(f"Object {name} has no GUI ViewObject.")
            changes.append((obj, visible))
    if missing:
        return _invalid(
            "Objects not found by exact internal name: " + ", ".join(missing),
            missing_objects=missing,
        )
    return {"ok": True, "changes": changes}


def _apply_visibility(changes: list[tuple[Any, bool]]) -> dict[str, list[str]]:
    shown: list[str] = []
    hidden: list[str] = []
    for obj, visible in changes:
        obj.ViewObject.Visibility = visible
        (shown if visible else hidden).append(obj.Name)
    return {"shown": shown, "hidden": hidden}


def _unique_names(objects: list[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for obj in objects:
        name = str(getattr(obj, "Name", "") or "").strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _invalid(error: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "retry_same_call": False,
        **details,
    }
