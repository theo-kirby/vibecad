# SPDX-License-Identifier: LGPL-2.1-or-later

set(VibeCAD_Scripts
    Init.py
    InitGui.py
    VibeCADAuth.py
    VibeCADCore.py
    VibeCADGui.py
    VibeCADPreferences.py
    VibeCADProvider.py
    VibeCADProject.py
    VibeCADSession.py
    VibeCADTools.py
    VibeCADTransactions.py
    VibeCADWorkbenchTools.py
    TestVibeCAD.py
    requirements.txt
)

set(VibeCAD_Resources
    preferences-vibecad.svg
    vibecad-open-assistant.svg
    vibecad-send.svg
    vibecad-stop.svg
    vibecad-activity.svg
)

file(GLOB VibeCAD_ProviderToolScripts
    CONFIGURE_DEPENDS
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    provider_tools/*.py
)

file(GLOB_RECURSE VibeCAD_ToolImplScripts
    CONFIGURE_DEPENDS
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    tool_impl/*.py
)

file(GLOB VibeCAD_TestScripts
    CONFIGURE_DEPENDS
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    vibecad_tests/*.py
)

add_custom_target(VibeCADScripts ALL
    SOURCES ${VibeCAD_Scripts} ${VibeCAD_ProviderToolScripts} ${VibeCAD_ToolImplScripts} ${VibeCAD_TestScripts} ${VibeCAD_Resources}
)

fc_target_copy_resource(VibeCADScripts
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/VibeCAD
    ${VibeCAD_Scripts}
    ${VibeCAD_ProviderToolScripts}
    ${VibeCAD_ToolImplScripts}
    ${VibeCAD_TestScripts}
    ${VibeCAD_Resources}
)

install(
    FILES
        ${VibeCAD_Scripts}
        ${VibeCAD_Resources}
    DESTINATION
        Mod/VibeCAD
)

install(
    DIRECTORY
        provider_tools
    DESTINATION
        Mod/VibeCAD
    FILES_MATCHING
        PATTERN "*.py"
)

install(
    DIRECTORY
        tool_impl
    DESTINATION
        Mod/VibeCAD
    FILES_MATCHING
        PATTERN "*.py"
)

install(
    DIRECTORY
        vibecad_tests
    DESTINATION
        Mod/VibeCAD
    FILES_MATCHING
        PATTERN "*.py"
)
