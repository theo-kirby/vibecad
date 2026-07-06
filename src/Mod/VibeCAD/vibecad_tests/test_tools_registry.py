# SPDX-License-Identifier: LGPL-2.1-or-later

import unittest

from VibeCADTools import SafetyLevel, ToolRegistry, VibeCADTool


class TestVibeCADTools(unittest.TestCase):
    def test_registry_rejects_duplicate_tool_names(self):
        registry = ToolRegistry()
        tool = VibeCADTool("core.test", "test", lambda: None, SafetyLevel.READ)
        registry.register(tool)
        with self.assertRaises(ValueError):
            registry.register(tool)

    def test_tool_schema_contains_safety_level(self):
        tool = VibeCADTool("core.test", "test", lambda: None, SafetyLevel.VIEW)
        self.assertEqual(tool.to_schema()["safety"], "view")
