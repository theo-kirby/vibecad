#!/usr/bin/env bash

set -euo pipefail
set -x

app_name="VibeCAD.app"
default_env="../.pixi/envs/default"
conda_env="${app_name}/Contents/Resources"
module_directory="${default_env}/Mod/VibeCAD"

rm -rf "${app_name}"

../scripts/install_vibecad_provider_deps.sh "${default_env}"
../scripts/install_vibecad_build123d_runtime.sh \
    "${default_env}/bin/python" \
    "${module_directory}"
../scripts/install_vibecad_openscad_runtime.sh \
    "${default_env}/bin/python" \
    "${module_directory}"
../scripts/install_vibecad_codex_runtime.sh \
    "${default_env}/bin/python" \
    "${module_directory}"
"${default_env}/bin/python" \
    ../scripts/write_vibecad_build123d_manifest.py \
    "${module_directory}/build123d_runtime" \
    "${default_env}" \
    "${default_env}/bin/python"

mkdir -p "${conda_env}"

cp -a "${default_env}/." "${conda_env}/"

# delete unnecessary stuff
rm -rf "${conda_env}/include"
find "${conda_env}" -name \*.a -delete

mv "${conda_env}/bin" "${conda_env}/bin_tmp"
mkdir "${conda_env}/bin"
cp "${conda_env}/bin_tmp/freecad" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/freecadcmd" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/ccx" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/python" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/pip" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/pyside6-rcc" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/gmsh" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/dot" "${conda_env}/bin/"
cp "${conda_env}/bin_tmp/unflatten" "${conda_env}/bin/"
rm -rf "${conda_env}/bin_tmp"

sed -i '1s|.*|#!/usr/bin/env python|' "${conda_env}/bin/pip"

# copy resources
cp resources/* "${conda_env}"

iconset="$(mktemp -d)/VibeCAD.iconset"
mkdir -p "${iconset}"
"${default_env}/bin/python" - \
    "../../../src/Gui/Icons/vibecad.svg" \
    "${iconset}" <<'PY'
from pathlib import Path
import sys

from PySide6 import QtCore, QtGui, QtSvg

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
renderer = QtSvg.QSvgRenderer(str(source))
if not renderer.isValid():
    raise SystemExit(f"VibeCAD app icon is not a valid SVG: {source}")
outputs = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}
for name, size in outputs.items():
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(destination / name), "PNG"):
        raise SystemExit(f"Could not write VibeCAD app icon: {name}")
PY
iconutil -c icns --output "${conda_env}/vibecad.icns" "${iconset}"
rm -rf "$(dirname "${iconset}")"

# Remove __pycache__ folders and .pyc files
find "${conda_env}" -path "*/__pycache__/*" -delete
find "${conda_env}" -name "*.pyc" -type f -delete

# fix problematic rpaths and reexport_dylibs for signing
# see https://github.com/FreeCAD/FreeCAD/issues/10144#issuecomment-1836686775
# and https://github.com/FreeCAD/FreeCAD-Bundle/pull/203
# and https://github.com/FreeCAD/FreeCAD-Bundle/issues/375
python ../scripts/fix_macos_lib_paths.py "${conda_env}/lib" -r

# build and install the launcher
cmake -B build launcher
cmake --build build
mkdir -p "${app_name}/Contents/MacOS"
cp build/FreeCAD "${app_name}/Contents/MacOS/FreeCAD"

# Add deployment target suffix to artifact name (e.g., "-macOS11" or "-macOS15")
deploy_target="${MACOS_DEPLOYMENT_TARGET:-11.0}"
version_name="VibeCAD_${BUILD_TAG}-macOS${deploy_target%%.*}-$(uname -m)"
application_menu_name="VibeCAD"

echo -e "\################"
echo -e "version_name:  ${version_name}"
echo -e "################"

# Extract Apple-compliant bundle version from version.json
# For dev/weekly builds, append a "d" + ISO week number suffix (e.g. "1.2.0d12")
# per Apple's CFBundleVersion spec for development builds
bundle_version=$(python3 -c "
import json, datetime
d = json.load(open('../../../version.json'))
v = f'{d[\"version_major\"]}.{d[\"version_minor\"]}.{d[\"version_patch\"]}'
suffix = d.get('version_suffix', '')
if suffix:
    week = datetime.date.today().isocalendar()[1]
    v += f'd{week}'
print(v)
")

cp Info.plist.template "${conda_env}/../Info.plist"
sed -i "s/FREECAD_BUNDLE_VERSION/${bundle_version}/" "${conda_env}/../Info.plist"
sed -i "s/APPLICATION_MENU_NAME/${application_menu_name}/" "${conda_env}/../Info.plist"

pixi list -e default > "${app_name}/Contents/packages.txt"
sed -i '1s/.*/\nLIST OF PACKAGES:/' "${app_name}/Contents/packages.txt"

echo "Running VibeCAD command-line smoke tests..."
if ! "${conda_env}/bin/freecadcmd" --safe-mode --version; then
    echo "VibeCAD command-line smoke test failed; the macOS bundle cannot start."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "from pivy import coin; print('VibeCAD Pivy/Coin import ok')"; then
    echo "VibeCAD Pivy smoke test failed; the macOS bundle cannot inspect the viewport."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "import importlib.util, openai, anthropic, keyring, jsonschema; import keyring.backends.macOS; assert keyring.backends.macOS.Keyring.priority > 0; assert importlib.util.find_spec('agents') is None; print('VibeCAD provider SDK, macOS Keychain backend, and schema validator imports ok')"; then
    echo "VibeCAD provider SDK/keyring smoke test failed; the macOS bundle is missing AI provider dependencies."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "from VibeCADProvider import _provider_multiprocessing_context, _provider_subprocess_smoke; assert _provider_multiprocessing_context().get_start_method() == 'spawn'; _provider_subprocess_smoke(); print('VibeCAD macOS spawn provider subprocess smoke ok')"; then
    echo "VibeCAD provider subprocess smoke test failed; the macOS bundle cannot run AI providers."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "from VibeCADBuild123d import runtime_execution_smoke; result = runtime_execution_smoke(); print('VibeCAD build123d runtime smoke ok', result['version'])"; then
    echo "VibeCAD build123d runtime smoke test failed; the macOS bundle cannot run build123d models."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "from VibeCADOpenSCAD import runtime_execution_smoke; result = runtime_execution_smoke(); print('VibeCAD OpenSCAD runtime smoke ok', result['version'])"; then
    echo "VibeCAD OpenSCAD runtime smoke test failed; the macOS bundle cannot run OpenSCAD models."
    exit 1
fi
if ! "${conda_env}/bin/freecadcmd" --safe-mode -c "from VibeCADCodex import runtime_execution_smoke; result = runtime_execution_smoke(); print('VibeCAD Codex app-server smoke ok', result['version'])"; then
    echo "VibeCAD Codex app-server smoke test failed; the macOS bundle cannot use ChatGPT subscriptions."
    exit 1
fi

# move plugins into their final location (Library only exists for macOS < 15.0 builds)
if [ -d "${conda_env}/Library" ]; then
    mv "${conda_env}/Library" "${conda_env}/.."
fi

# move App Extensions (PlugIns) to the correct location for macOS registration
if [ -d "${conda_env}/PlugIns" ]; then
    mv "${conda_env}/PlugIns" "${conda_env}/.."
fi

if [[ "${MACOS_SIGN_RELEASE:-false}" == "true" ]]; then
    # create the signed dmg
    ../../scripts/macos_sign_and_notarize.zsh \
        -p "${MACOS_KEYCHAIN_PROFILE:-VibeCAD}" \
        -k "${MACOS_SIGNING_KEY_ID:?MACOS_SIGNING_KEY_ID is required for signing}" \
        -n "${app_name}" \
        -v "VibeCAD" \
        -o "${version_name}.dmg"
else
    # Ad-hoc sign for local builds (required for QuickLook extensions to register)
    if [ -d "${app_name}/Contents/PlugIns" ]; then
        echo "Ad-hoc signing App Extensions with entitlements..."
        codesign --force --sign - \
            --entitlements ../../../src/MacAppBundle/QuickLook/modern/ThumbnailExtension.entitlements \
            "${app_name}/Contents/PlugIns/FreeCADThumbnailExtension.appex"
        codesign --force --sign - \
            --entitlements ../../../src/MacAppBundle/QuickLook/modern/PreviewExtension.entitlements \
            "${app_name}/Contents/PlugIns/FreeCADPreviewExtension.appex"
    fi
    echo "Ad-hoc signing app bundle..."
    codesign --force --sign - "${app_name}/Contents/packages.txt"
    if [ -f "${app_name}/Contents/Library/QuickLook/QuicklookFCStd.qlgenerator/Contents/MacOS/QuicklookFCStd" ]; then
        codesign --force --sign - "${app_name}/Contents/Library/QuickLook/QuicklookFCStd.qlgenerator/Contents/MacOS/QuicklookFCStd"
    fi
    codesign --force --deep --sign - "${app_name}"
    codesign --verify --deep --strict "${app_name}"

    # create the dmg
    dmgbuild \
        -s dmg_settings.py \
        -Dapp_name="${app_name}" \
        "VibeCAD" \
        "${version_name}.dmg"
fi

# create hash
sha256sum ${version_name}.dmg > ${version_name}.dmg-SHA256.txt

if [[ "${UPLOAD_RELEASE:-false}" == "true" ]]; then
    for attempt in 1 2 3 4 5; do
        if gh release upload --clobber "${BUILD_TAG}" "${version_name}.dmg" "${version_name}.dmg-SHA256.txt"; then
            break
        fi
        if [[ $attempt -eq 5 ]]; then
            echo "Failed to upload release after 5 attempts" >&2
            exit 1
        fi
        echo "Upload attempt $attempt failed, retrying in $((attempt * 10))s..."
        sleep $((attempt * 10))
    done
fi
