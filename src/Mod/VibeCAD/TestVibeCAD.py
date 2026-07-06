# SPDX-License-Identifier: LGPL-2.1-or-later
"""Aggregator module for VibeCAD's unit tests.

FreeCAD's unittest runner discovers tests by module name (``App.__unit_test__``
registers ``"TestVibeCAD"``), and ``tools/vibecad_selected_tests.py`` addresses
tests as ``TestVibeCAD.ClassName.test_name``. The test classes themselves live
in topic modules under ``vibecad_tests``; importing them here keeps both entry
points working unchanged.
"""

import unittest

from vibecad_tests.test_auth import TestVibeCADAuth  # noqa: F401
from vibecad_tests.test_preferences import TestVibeCADPreferences  # noqa: F401
from vibecad_tests.test_tools_registry import TestVibeCADTools  # noqa: F401
from vibecad_tests.test_project_storage import (  # noqa: F401
    TestVibeCADProject,
    TestVibeCADStorageLayout,
)
from vibecad_tests.test_provider_misc import (  # noqa: F401
    TestVibeCADAnthropicProvider,
    TestVibeCADProviderDispatch,
    TestVibeCADReferenceImages,
)
from vibecad_tests.test_gui_thumbnails import TestVibeCADThumbnailMetadata  # noqa: F401
from vibecad_tests.test_service_context import TestVibeCADServiceContext  # noqa: F401
from vibecad_tests.test_provider_payloads import TestVibeCADProviderPayloads  # noqa: F401
from vibecad_tests.test_session_loop import TestVibeCADSessionLoop  # noqa: F401
from vibecad_tests.test_live_acceptance import TestVibeCADLiveAcceptance  # noqa: F401
from vibecad_tests.test_sketcher_tools import TestVibeCADSketcherTools  # noqa: F401
from vibecad_tests.test_partdesign_assembly import (  # noqa: F401
    TestVibeCADPartDesignAssembly,
)
from vibecad_tests.test_workbench_summaries import (  # noqa: F401
    TestVibeCADWorkbenchSummaries,
)
from vibecad_tests.test_workbench_packs import TestVibeCADWorkbenchPacks  # noqa: F401
from vibecad_tests.test_surface_tools import TestVibeCADSurfaceModeling  # noqa: F401
from vibecad_tests.test_cam_tools import TestVibeCADCAMTools  # noqa: F401
from vibecad_tests.test_gui_panel import TestVibeCADAssistantPanel  # noqa: F401
from vibecad_tests.test_core_misc import TestVibeCADCoreMisc  # noqa: F401

if __name__ == "__main__":
    unittest.main()
