# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.clear_local_session``."""

from __future__ import annotations


TOOL_SPEC = {'description': 'Clear the local VibeCAD conversation, attached viewport '
                'screenshot metadata, and user reference images.',
 'name': 'core.clear_local_session',
 'safety': 'WRITE'}


def run(service, **kwargs):
    screenshot = service._last_view_screenshot
    service._last_view_screenshot = None
    references_cleared = 0
    try:
        references_cleared = int(service.clear_reference_images().get("cleared", 0))
    except AttributeError:
        pass
    service._conversation_cache = []
    service._conversation_cache_key = None
    service._tool_shape_feedback = []
    path = service._conversation_path()
    service._conversation_cache_key = str(path)
    service._write_conversation(path, [])
    return {
        "ok": True,
        "screenshot_cleared": bool(screenshot),
        "reference_images_cleared": references_cleared,
        "conversation_cleared": True,
        "conversation_path": str(path),
        "tool_shape_feedback_cleared": True,
    }
