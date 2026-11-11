#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_PLIST="$PROJECT_DIR/PyCubSim2.app/Contents/Info.plist"
SPEC_FILE="$PROJECT_DIR/packaging/PyCubSim2.linux.spec"
DESKTOP_FILE="$PROJECT_DIR/packaging/linux/io.github.yuta4869.PyCubSim2.desktop"
APP_RUN="$PROJECT_DIR/packaging/linux/AppRun"
METAINFO_TEMPLATE="$PROJECT_DIR/packaging/linux/io.github.yuta4869.PyCubSim2.appdata.xml.in"
ICON_SOURCE="$PROJECT_DIR/assets/PyCubSim2-app-icon.png"
BUILD_ROOT="$PROJECT_DIR/build/ubuntu"
PYINSTALLER_DIST="$BUILD_ROOT/pyinstaller-dist"
WORK_ROOT="$BUILD_ROOT/work"
APP_DIR="$BUILD_ROOT/PyCubSim2.AppDir"
DEB_ROOT="$BUILD_ROOT/deb-root"
DIST_ROOT="$PROJECT_DIR/dist"

if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' "Ubuntu packages must be built on Linux." >&2
    exit 1
fi

PYTHON_BIN="${PYTHON:-$(command -v python3)}"
if ! "$PYTHON_BIN" -c "import PyInstaller, PIL" 2>/dev/null; then
    printf '%s\n' "Build dependencies are missing. Run:" >&2
    printf '  %q -m pip install -r requirements.txt -r requirements-build.txt\n' \
        "$PYTHON_BIN" >&2
    exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    printf '%s\n' "dpkg-deb is required to build the Ubuntu package." >&2
    exit 1
fi
if ! command -v file >/dev/null 2>&1; then
    printf '%s\n' "The file command is required to build the AppImage." >&2
    exit 1
fi

VERSION="$(
    "$PYTHON_BIN" -c \
        'import plistlib, sys; print(plistlib.load(open(sys.argv[1], "rb"))["CFBundleShortVersionString"])' \
        "$SOURCE_PLIST"
)"
MACHINE="$(uname -m)"
case "$MACHINE" in
    x86_64)
        APPIMAGE_ARCH="x86_64"
        DEB_ARCH="amd64"
        ;;
    aarch64|arm64)
        APPIMAGE_ARCH="aarch64"
        DEB_ARCH="arm64"
        ;;
    *)
        printf 'Unsupported Ubuntu architecture: %s\n' "$MACHINE" >&2
        exit 1
        ;;
esac

PYINSTALLER_APP="$PYINSTALLER_DIST/PyCubSim2"
PYINSTALLER_CLI="$PYINSTALLER_APP/PyCubSim2-cli"
LINUX_ICON="$BUILD_ROOT/pycubsim2.png"
METAINFO_FILE="$BUILD_ROOT/io.github.yuta4869.PyCubSim2.appdata.xml"
PORTABLE_DIR="$DIST_ROOT/PyCubSim2-${VERSION}-ubuntu-${APPIMAGE_ARCH}"
PORTABLE_ARCHIVE="${PORTABLE_DIR}.tar.gz"
APPIMAGE_PATH="$DIST_ROOT/PyCubSim2-${VERSION}-${APPIMAGE_ARCH}.AppImage"
DEB_PATH="$DIST_ROOT/pycubsim2_${VERSION}_${DEB_ARCH}.deb"
CHECKSUM_PATH="$DIST_ROOT/PyCubSim2-${VERSION}-ubuntu-${APPIMAGE_ARCH}.sha256"
SMOKE_IMAGE="$BUILD_ROOT/standalone-smoke.png"
APPIMAGE_SMOKE_IMAGE="$BUILD_ROOT/appimage-smoke.png"

rm -rf "$BUILD_ROOT" "$PORTABLE_DIR"
rm -f "$PORTABLE_ARCHIVE" "$APPIMAGE_PATH" "$DEB_PATH" "$CHECKSUM_PATH"
mkdir -p "$PYINSTALLER_DIST" "$WORK_ROOT" "$DIST_ROOT"

"$PYTHON_BIN" "$PROJECT_DIR/tools/generate_platform_icons.py" \
    --source "$ICON_SOURCE" \
    --png "$LINUX_ICON" \
    --png-size 512
sed "s/@VERSION@/$VERSION/g" "$METAINFO_TEMPLATE" >"$METAINFO_FILE"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE"
fi
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate "$METAINFO_FILE"
fi

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$PYINSTALLER_DIST" \
    --workpath "$WORK_ROOT" \
    "$SPEC_FILE"

"$PYINSTALLER_CLI" \
    --headless \
    --steps 5 \
    --agent "$PYINSTALLER_APP/_internal/examples/agents/beacon_agent/agent.json" \
    --output "$SMOKE_IMAGE"
if [[ ! -s "$SMOKE_IMAGE" ]]; then
    printf '%s\n' "The standalone Linux smoke test did not create an image." >&2
    exit 1
fi

mkdir -p "$PORTABLE_DIR"
cp -a --no-preserve=xattr "$PYINSTALLER_APP/." "$PORTABLE_DIR/"
tar -C "$DIST_ROOT" -czf "$PORTABLE_ARCHIVE" "$(basename "$PORTABLE_DIR")"

mkdir -p \
    "$APP_DIR/usr/bin" \
    "$APP_DIR/usr/lib/pycubsim2" \
    "$APP_DIR/usr/share/applications" \
    "$APP_DIR/usr/share/icons/hicolor/512x512/apps" \
    "$APP_DIR/usr/share/metainfo" \
    "$APP_DIR/usr/share/doc/pycubsim2"
cp -a --no-preserve=xattr "$PYINSTALLER_APP/." \
    "$APP_DIR/usr/lib/pycubsim2/"
ln -s ../lib/pycubsim2/PyCubSim2 "$APP_DIR/usr/bin/pycubsim2"
ln -s ../lib/pycubsim2/PyCubSim2-cli "$APP_DIR/usr/bin/pycubsim2-cli"
install -m 755 "$APP_RUN" "$APP_DIR/AppRun"
install -m 644 "$DESKTOP_FILE" \
    "$APP_DIR/io.github.yuta4869.PyCubSim2.desktop"
install -m 644 "$DESKTOP_FILE" \
    "$APP_DIR/usr/share/applications/io.github.yuta4869.PyCubSim2.desktop"
install -m 644 "$LINUX_ICON" "$APP_DIR/pycubsim2.png"
install -m 644 "$LINUX_ICON" \
    "$APP_DIR/usr/share/icons/hicolor/512x512/apps/pycubsim2.png"
install -m 644 "$METAINFO_FILE" \
    "$APP_DIR/usr/share/metainfo/io.github.yuta4869.PyCubSim2.appdata.xml"
install -m 644 "$PROJECT_DIR/LICENSE" \
    "$APP_DIR/usr/share/doc/pycubsim2/LICENSE"
install -m 644 "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" \
    "$APP_DIR/usr/share/doc/pycubsim2/THIRD_PARTY_NOTICES.md"
ln -s pycubsim2.png "$APP_DIR/.DirIcon"

APPIMAGE_TOOL="${APPIMAGETOOL:-}"
if [[ -z "$APPIMAGE_TOOL" ]]; then
    APPIMAGE_TOOL="$BUILD_ROOT/appimagetool-${APPIMAGE_ARCH}.AppImage"
    curl \
        --fail \
        --location \
        --retry 3 \
        --output "$APPIMAGE_TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage"
    chmod +x "$APPIMAGE_TOOL"
fi

ARCH="$APPIMAGE_ARCH" APPIMAGE_EXTRACT_AND_RUN=1 \
    "$APPIMAGE_TOOL" \
    --mksquashfs-opt=-no-xattrs \
    "$APP_DIR" \
    "$APPIMAGE_PATH"
chmod +x "$APPIMAGE_PATH"

APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE_PATH" \
    --headless \
    --steps 5 \
    --output "$APPIMAGE_SMOKE_IMAGE"
if [[ ! -s "$APPIMAGE_SMOKE_IMAGE" ]]; then
    printf '%s\n' "The AppImage smoke test did not create an image." >&2
    exit 1
fi

mkdir -p \
    "$DEB_ROOT/DEBIAN" \
    "$DEB_ROOT/opt/pycubsim2" \
    "$DEB_ROOT/usr/bin" \
    "$DEB_ROOT/usr/share/applications" \
    "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps" \
    "$DEB_ROOT/usr/share/metainfo" \
    "$DEB_ROOT/usr/share/doc/pycubsim2"
cp -a --no-preserve=xattr "$PYINSTALLER_APP/." \
    "$DEB_ROOT/opt/pycubsim2/"
ln -s /opt/pycubsim2/PyCubSim2 "$DEB_ROOT/usr/bin/pycubsim2"
ln -s /opt/pycubsim2/PyCubSim2-cli "$DEB_ROOT/usr/bin/pycubsim2-cli"
install -m 644 "$DESKTOP_FILE" \
    "$DEB_ROOT/usr/share/applications/io.github.yuta4869.PyCubSim2.desktop"
install -m 644 "$LINUX_ICON" \
    "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps/pycubsim2.png"
install -m 644 "$METAINFO_FILE" \
    "$DEB_ROOT/usr/share/metainfo/io.github.yuta4869.PyCubSim2.appdata.xml"
install -m 644 "$PROJECT_DIR/LICENSE" \
    "$DEB_ROOT/usr/share/doc/pycubsim2/LICENSE"
install -m 644 "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" \
    "$DEB_ROOT/usr/share/doc/pycubsim2/THIRD_PARTY_NOTICES.md"
install -m 755 "$PROJECT_DIR/packaging/linux/debian/postinst" \
    "$DEB_ROOT/DEBIAN/postinst"
install -m 755 "$PROJECT_DIR/packaging/linux/debian/postrm" \
    "$DEB_ROOT/DEBIAN/postrm"

INSTALLED_SIZE="$(du -sk "$DEB_ROOT/opt/pycubsim2" | cut -f1)"
cat >"$DEB_ROOT/DEBIAN/control" <<EOF
Package: pycubsim2
Version: $VERSION
Section: science
Priority: optional
Architecture: $DEB_ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: yuta4869 <yuta4869@users.noreply.github.com>
Depends: libc6 (>= 2.35), libfontconfig1, libgcc-s1, libgl1, libglib2.0-0, libsm6, libstdc++6, libx11-6, libxcb1, libxext6, libxfixes3, libxi6, libxrandr2, libxrender1, libxss1, zlib1g
Homepage: https://github.com/yuta4869/PyCubSim2
Description: extensible PyBullet simulation environment for PyCub
 PyCubSim2 provides scene editing, multiple robots, RGB-D sensors,
 webcam input, configurable behaviors, and external agent bundles.
EOF

dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_PATH"

DEB_SMOKE_ROOT="$BUILD_ROOT/deb-smoke"
DEB_SMOKE_IMAGE="$BUILD_ROOT/deb-smoke.png"
mkdir -p "$DEB_SMOKE_ROOT"
dpkg-deb --extract "$DEB_PATH" "$DEB_SMOKE_ROOT"
"$DEB_SMOKE_ROOT/opt/pycubsim2/PyCubSim2-cli" \
    --headless \
    --steps 5 \
    --agent "$DEB_SMOKE_ROOT/opt/pycubsim2/_internal/examples/agents/beacon_agent/agent.json" \
    --output "$DEB_SMOKE_IMAGE"
if [[ ! -s "$DEB_SMOKE_IMAGE" ]]; then
    printf '%s\n' "The extracted deb smoke test did not create an image." >&2
    exit 1
fi

(
    cd "$DIST_ROOT"
    sha256sum \
        "$(basename "$APPIMAGE_PATH")" \
        "$(basename "$DEB_PATH")" \
        "$(basename "$PORTABLE_ARCHIVE")" \
        >"$(basename "$CHECKSUM_PATH")"
)

printf '\n%s\n' "Ubuntu packages:"
printf '  AppImage: %s\n' "$APPIMAGE_PATH"
printf '  Debian:   %s\n' "$DEB_PATH"
printf '  Portable: %s\n' "$PORTABLE_ARCHIVE"
printf '  SHA-256:  %s\n' "$CHECKSUM_PATH"
