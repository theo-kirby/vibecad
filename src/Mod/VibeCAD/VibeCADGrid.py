# SPDX-License-Identifier: LGPL-2.1-or-later

"""Fusion-style always-on 3D grid for VibeCAD.

Reuses the Draft workbench grid machinery (``Gui.Snapper`` + ``gridTracker``)
to keep a reference grid visible in every 3D view regardless of the active
workbench, similar to Fusion 360's viewport grid.

Behavior:

- Draft grid preferences (``alwaysShowGrid`` and ``GridHideInOtherWorkbenches``)
  are seeded exactly once, guarded by a flag parameter, so later manual
  changes made by the user in Draft preferences are never overridden.
- A lightweight observer on the MDI area initializes the grid for each 3D
  view at most once. Manually toggling the grid off in a view (e.g. via
  Draft's Toggle Grid) is respected: already-initialized views are skipped.
- The whole feature sits behind the ``Mod/VibeCAD`` ``AlwaysShowGrid``
  boolean preference (default: enabled) as a master kill-switch.

The module imports safely outside FreeCAD (guarded imports) so tooling such
as linters and test collectors can load it.
"""

from __future__ import annotations

from typing import Any

try:
    import FreeCAD as App
except ImportError:  # pragma: no cover - only outside FreeCAD (tooling/tests)
    App = None  # type: ignore[assignment]

_PARAM_ROOT = "User parameter:BaseApp/Preferences/"
_VIBECAD_PARAM_PATH = _PARAM_ROOT + "Mod/VibeCAD"
_DRAFT_PARAM_PATH = _PARAM_ROOT + "Mod/Draft"
_SEED_FLAG = "GridPreferencesSeeded"

# Fast-path identity cache of views already handled by this module. The
# authoritative "grid already exists for this view" check is membership in
# ``Gui.Snapper.trackers[0]`` (equality-based, stable across Python wrapper
# objects); this id() set merely short-circuits repeated activations of the
# same wrapper. Each view is initialized at most once either way.
_seen_views: set[int] = set()
_observer_installed = False


def _warn(message: str) -> None:
    """Print a console warning when FreeCAD is available."""
    if App is not None:
        App.Console.PrintWarning(f"VibeCAD grid: {message}\n")


def is_enabled() -> bool:
    """Return True when the always-on grid feature is enabled."""
    if App is None:
        return False
    return App.ParamGet(_VIBECAD_PARAM_PATH).GetBool("AlwaysShowGrid", True)


def seed_grid_preferences() -> None:
    """Seed Draft grid preferences once so the grid shows app-wide.

    Write-once: guarded by a flag in the VibeCAD parameter group. If the user
    later disables the grid via Draft preferences, we never force it back on.
    """
    if App is None:
        return
    vibecad_params = App.ParamGet(_VIBECAD_PARAM_PATH)
    if vibecad_params.GetBool(_SEED_FLAG, False):
        return
    draft_params = App.ParamGet(_DRAFT_PARAM_PATH)
    draft_params.SetBool("alwaysShowGrid", True)
    draft_params.SetBool("GridHideInOtherWorkbenches", False)
    vibecad_params.SetBool(_SEED_FLAG, True)


def _get_snapper() -> Any:
    """Return the shared Draft Snapper, creating it if it does not exist."""
    import FreeCADGui as Gui

    snapper = getattr(Gui, "Snapper", None)
    if snapper is None:
        from draftguitools import gui_snapper

        snapper = gui_snapper.Snapper()
        Gui.Snapper = snapper
    return snapper


def _show_grid_in_active_view() -> None:
    """Initialize and show the grid for the active 3D view, at most once.

    Views whose grid tracker already exists are skipped so a manual grid
    toggle by the user is never fought.
    """
    if App is None or not App.GuiUp:
        return
    try:
        from draftutils import gui_utils

        view = gui_utils.get_3d_view()
        if view is None:
            return
        key = id(view)
        if key in _seen_views:
            return
        snapper = _get_snapper()
        if view in snapper.trackers[0]:
            # Grid tracker already exists (e.g. created by Draft itself or a
            # previous wrapper of the same view); respect its current state.
            _seen_views.add(key)
            return
        # Creates the per-view trackers; because alwaysShowGrid was seeded,
        # the new grid gets show_always=True and is displayed immediately.
        snapper.setTrackers()
        _seen_views.add(key)
    except Exception as exc:
        _warn(f"unable to show grid in active view: {exc}")


def _on_sub_window_activated(_window: Any = None) -> None:
    """Defer grid initialization until the view activation settles."""
    try:
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, _show_grid_in_active_view)
    except Exception as exc:
        _warn(f"deferred grid update failed: {exc}")


def setup() -> None:
    """Seed preferences (once) and install the view observer (idempotent)."""
    global _observer_installed
    if App is None or not App.GuiUp:
        return
    if not is_enabled():
        return
    seed_grid_preferences()
    if _observer_installed:
        return
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets

        main_window = Gui.getMainWindow()
        mdi_area = main_window.findChild(QtWidgets.QMdiArea)
        if mdi_area is None:
            _warn("MDI area not found; grid observer not installed")
            return
        mdi_area.subWindowActivated.connect(_on_sub_window_activated)
        _observer_installed = True
        # Handle a 3D view that is already active at setup time.
        _on_sub_window_activated()
    except Exception as exc:
        _warn(f"observer installation failed: {exc}")
