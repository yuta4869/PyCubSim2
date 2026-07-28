# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import os
import plistlib
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).parent
SOURCE_APP_PLIST = (
    PROJECT_ROOT / "PyCubSim2.app" / "Contents" / "Info.plist"
)
with SOURCE_APP_PLIST.open("rb") as stream:
    source_app_info = plistlib.load(stream)

data_files = [
    (str(PROJECT_ROOT / "assets"), "assets"),
    (str(PROJECT_ROOT / "actions"), "actions"),
    (
        str(PROJECT_ROOT / "layouts" / "default_scene.json"),
        "layouts",
    ),
    (str(PROJECT_ROOT / "examples" / "agents"), "examples/agents"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
icon_path = (
    PROJECT_ROOT
    / "PyCubSim2.app"
    / "Contents"
    / "Resources"
    / "PyCubSim2.icns"
)

a = Analysis(
    [str(PROJECT_ROOT / "run_sim.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pybullet_data"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PyCubSim2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("TARGET_ARCH") or None,
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
    entitlements_file=None,
    icon=[str(icon_path)],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PyCubSim2",
)
app = BUNDLE(
    coll,
    name="PyCubSim2.app",
    icon=str(icon_path),
    bundle_identifier="local.yuta.pycubsim2",
    info_plist={
        "CFBundleDisplayName": "PyCubSim2",
        "CFBundleShortVersionString": source_app_info[
            "CFBundleShortVersionString"
        ],
        "CFBundleVersion": source_app_info["CFBundleVersion"],
        "LSMinimumSystemVersion": "13.0",
        "LSMultipleInstancesProhibited": True,
        "NSCameraUsageDescription": (
            "PyCubSim2 can use the Mac camera as an optional RGB sensor."
        ),
        "NSCameraUseContinuityCameraDeviceType": True,
        "NSHighResolutionCapable": True,
    },
)
