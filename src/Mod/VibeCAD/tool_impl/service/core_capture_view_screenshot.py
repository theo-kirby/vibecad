# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.capture_view_screenshot``."""

from __future__ import annotations

from pathlib import Path
import re
import time

from VibeCADProject import vibecad_data_dir

from . import core_set_view


TOOL_SPEC = {'description': 'Capture the active viewport to a project PNG for visual '
                'verification. Defaults to axometric + fit all; pass '
                'orientation=none and fit_all=false to keep framing set by '
                'core.set_view.',
 'name': 'core.capture_view_screenshot',
 'parameters': {'properties': {'orientation': {'description': 'Camera orientation applied '
                'before capture: front, top, right, rear, bottom, left, '
                'isometric, axometric (default), or none to keep the current '
                'camera.',
                'type': 'string'},
                'fit_all': {'description': 'When true (default), zoom/fit the view to all '
                'visible geometry before capture. Set false to preserve the '
                'current zoom and framing.',
                'type': 'boolean'}},
                'type': 'object'},
 'safety': 'VIEW'}


def run(service, orientation=None, fit_all=True, **kwargs):
    orientation_name = str(orientation or "axometric").strip().lower()
    if orientation_name not in core_set_view.ALLOWED_ORIENTATIONS:
        result = {
            "ok": False,
            "captured": False,
            "path": None,
            "file_size": 0,
            "error": f"Unknown orientation {orientation_name!r}.",
            "allowed_orientations": list(core_set_view.ALLOWED_ORIENTATIONS),
        }
        service._last_view_screenshot = result
        return result
    try:
        import FreeCAD as App
        import FreeCADGui as Gui
    except Exception as exc:
        result = {"ok": False, "captured": False, "path": None, "file_size": 0, "error": str(exc)}
        service._last_view_screenshot = result
        return result

    try:
        screenshot_dir = _screenshot_artifact_dir(service)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        document_name = _slug(_active_document_name(App) or "view")
        path = screenshot_dir / f"{document_name}-{int(time.time() * 1000)}.png"
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            result = {
                "ok": False,
                "captured": False,
                "path": None,
                "file_size": 0,
                "error": "No active 3D view is available.",
            }
            service._last_view_screenshot = result
            return result
        try:
            if orientation_name != "none":
                getattr(view, core_set_view.ORIENTATION_METHODS[orientation_name])()
            if fit_all:
                view.fitAll()
        except Exception:
            pass
        view.saveImage(str(path), 1280, 900, "White")
        captured = path.exists()
        result = {
            "ok": captured,
            "captured": captured,
            "path": str(path) if captured else None,
            "file_size": path.stat().st_size if captured else 0,
            "size": [1280, 900],
            "format": "png",
            "background": "White",
            "orientation": orientation_name,
            "fit_all": bool(fit_all),
            "artifact_role": "visual_verification",
            "workbench": _active_workbench_name(Gui),
            "document": _active_document_name(App),
        }
        if captured:
            result["visual_observation"] = service._screenshot_visual_observation(path)
        else:
            result["error"] = "View saveImage did not create a file."
        service._last_view_screenshot = result
        return result
    except Exception as exc:
        result = {"ok": False, "captured": False, "path": None, "file_size": 0, "error": str(exc)}
        service._last_view_screenshot = result
        return result


def _active_workbench_name(gui):
    try:
        workbench = gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None


def _screenshot_artifact_dir(service) -> Path:
    """Screenshot folder inside the per-document project directory.

    Project roots always live under the central VibeCAD data dir, so
    screenshots are never written next to the CAD file. Without a project
    context, the default location is still inside ``vibecad_data_dir()``.
    """
    try:
        project_context = service.project_context()
    except Exception:
        project_context = {}
    root = project_context.get("root") if isinstance(project_context, dict) else None
    if root:
        return Path(str(root)).expanduser() / "screenshots"
    return vibecad_data_dir() / "screenshots"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return slug[:64] or "view"


def _active_document_name(app):
    try:
        document = app.ActiveDocument
        if document is not None:
            return document.Name
    except Exception:
        pass
    return None
