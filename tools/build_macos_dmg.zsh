#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_PLIST="$PROJECT_DIR/PyCubSim2.app/Contents/Info.plist"
SPEC_FILE="$PROJECT_DIR/packaging/PyCubSim2.spec"
BUILD_ROOT="$PROJECT_DIR/build/macos"
PYINSTALLER_DIST="$BUILD_ROOT/pyinstaller-dist"
WORK_ROOT="$BUILD_ROOT/work"
DMG_ROOT="$BUILD_ROOT/dmg-root"
DIST_ROOT="$PROJECT_DIR/dist"

if [[ "$(uname -s)" != "Darwin" ]]; then
    print -u2 "The macOS DMG must be built on macOS."
    exit 1
fi

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
elif [[ -x "/opt/miniconda3/envs/pycubsim2/bin/python" ]]; then
    PYTHON_BIN="/opt/miniconda3/envs/pycubsim2/bin/python"
elif [[ -x "/opt/miniconda3/envs/pycub-homeostatic/bin/python" ]]; then
    PYTHON_BIN="/opt/miniconda3/envs/pycub-homeostatic/bin/python"
else
    PYTHON_BIN="$(command -v python3)"
fi

if ! "$PYTHON_BIN" -c "import PyInstaller" 2>/dev/null; then
    print -u2 "PyInstaller is missing. Run:"
    print -u2 "  $PYTHON_BIN -m pip install -r requirements-build.txt"
    exit 1
fi

VERSION="$(/usr/libexec/PlistBuddy \
    -c "Print :CFBundleShortVersionString" "$SOURCE_PLIST")"
ARCH="${TARGET_ARCH:-$(uname -m)}"
APP_NAME="PyCubSim2.app"
APP_PATH="$PYINSTALLER_DIST/$APP_NAME"
FINAL_APP="$DIST_ROOT/$APP_NAME"
DMG_PATH="$DIST_ROOT/PyCubSim2-${VERSION}-macos-${ARCH}.dmg"
SIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
SELF_TEST_IMAGE="$BUILD_ROOT/standalone-smoke.png"

if [[ -n "${NOTARY_PROFILE:-}" && "$SIGN_IDENTITY" == "-" ]]; then
    print -u2 "NOTARY_PROFILE requires a Developer ID CODESIGN_IDENTITY."
    exit 1
fi

rm -rf "$BUILD_ROOT" "$FINAL_APP"
rm -f "$DMG_PATH"
mkdir -p "$PYINSTALLER_DIST" "$WORK_ROOT" "$DMG_ROOT" "$DIST_ROOT"

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$PYINSTALLER_DIST" \
    --workpath "$WORK_ROOT" \
    "$SPEC_FILE"

xattr -cr "$APP_PATH"
if [[ "$SIGN_IDENTITY" == "-" ]]; then
    codesign --force --deep --sign - "$APP_PATH"
else
    codesign \
        --force \
        --deep \
        --options runtime \
        --timestamp \
        --sign "$SIGN_IDENTITY" \
        "$APP_PATH"
fi
codesign --verify --deep --strict "$APP_PATH"

env -i \
    HOME="$HOME" \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin \
    TMPDIR=/tmp \
    "$APP_PATH/Contents/MacOS/PyCubSim2" \
    --headless \
    --steps 5 \
    --agent "$APP_PATH/Contents/Resources/examples/agents/beacon_agent/agent.json" \
    --output "$SELF_TEST_IMAGE"
if [[ ! -s "$SELF_TEST_IMAGE" ]]; then
    print -u2 "The standalone headless smoke test did not create an image."
    exit 1
fi

/usr/bin/ditto "$APP_PATH" "$FINAL_APP"
/usr/bin/ditto "$APP_PATH" "$DMG_ROOT/$APP_NAME"
ln -s /Applications "$DMG_ROOT/Applications"

hdiutil create \
    -volname "PyCubSim2" \
    -srcfolder "$DMG_ROOT" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

if [[ "$SIGN_IDENTITY" != "-" ]]; then
    codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
fi

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit \
        "$DMG_PATH" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait
    xcrun stapler staple "$DMG_PATH"
fi

hdiutil verify "$DMG_PATH"
print
print "Application: $FINAL_APP"
print "Disk image:  $DMG_PATH"
